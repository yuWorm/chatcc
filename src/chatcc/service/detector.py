from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CommandEntry:
    name: str
    command: str
    source: str


@dataclass
class ProjectProfile:
    path: str
    project_type: str = "unknown"
    readme_summary: str = ""
    available_commands: list[CommandEntry] = field(default_factory=list)


class ProjectDetector:
    _MAX_README_LINES = 200

    _TYPE_PRIORITY = [
        ("package.json", "node"),
        ("pyproject.toml", "python"),
        ("requirements.txt", "python"),
        ("setup.py", "python"),
        ("go.mod", "go"),
        ("Cargo.toml", "rust"),
        ("Makefile", "makefile"),
    ]

    def detect(self, project_path: str) -> ProjectProfile:
        root = Path(project_path)
        profile = ProjectProfile(path=project_path)

        profile.readme_summary, readme_cmds = self._parse_readme(root)
        profile.available_commands.extend(readme_cmds)

        for marker, ptype in self._TYPE_PRIORITY:
            if (root / marker).exists() and profile.project_type == "unknown":
                profile.project_type = ptype

        config_cmds = self._parse_config_files(root)
        seen = {(c.name, c.command) for c in profile.available_commands}
        for cmd in config_cmds:
            if (cmd.name, cmd.command) not in seen:
                profile.available_commands.append(cmd)
                seen.add((cmd.name, cmd.command))

        return profile

    # ── README parsing ──────────────────────────────────────────────

    _CMD_PATTERN = re.compile(
        r"^\s*\$?\s*((?:npm|yarn|pnpm)\s+run\s+\S+"
        r"|(?:python|python3|uvicorn|gunicorn|flask|django-admin)\s+\S+.*"
        r"|go\s+run\s+\S+.*"
        r"|cargo\s+(?:run|build|test)\b.*"
        r"|make\s+\S+.*)",
        re.MULTILINE,
    )

    def _parse_readme(self, root: Path) -> tuple[str, list[CommandEntry]]:
        readme = root / "README.md"
        if not readme.exists():
            return "", []

        try:
            text = readme.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "", []

        lines = text.splitlines()[: self._MAX_README_LINES]
        summary_lines: list[str] = []
        for line in lines[:20]:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                summary_lines.append(stripped)
            if len(summary_lines) >= 3:
                break
        summary = " ".join(summary_lines)

        cmds: list[CommandEntry] = []
        seen: set[str] = set()
        for m in self._CMD_PATTERN.finditer("\n".join(lines)):
            raw = m.group(1).strip()
            if raw not in seen:
                parts = raw.split()
                name = parts[-1] if len(parts) <= 3 else parts[1]
                cmds.append(CommandEntry(name=name, command=raw, source="readme"))
                seen.add(raw)

        return summary, cmds

    # ── Config file parsers ─────────────────────────────────────────

    def _parse_config_files(self, root: Path) -> list[CommandEntry]:
        cmds: list[CommandEntry] = []
        cmds.extend(self._parse_package_json(root))
        cmds.extend(self._parse_pyproject_toml(root))
        cmds.extend(self._parse_makefile(root))
        cmds.extend(self._parse_go_mod(root))
        cmds.extend(self._parse_cargo_toml(root))
        return cmds

    def _parse_package_json(self, root: Path) -> list[CommandEntry]:
        pkg_file = root / "package.json"
        if not pkg_file.exists():
            return []
        try:
            data = json.loads(pkg_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        scripts = data.get("scripts", {})
        return [
            CommandEntry(name=k, command=f"npm run {k}", source="package.json")
            for k in scripts
        ]

    def _parse_pyproject_toml(self, root: Path) -> list[CommandEntry]:
        toml_file = root / "pyproject.toml"
        if not toml_file.exists():
            return []
        try:
            import tomllib

            data = tomllib.loads(toml_file.read_text(encoding="utf-8"))
        except Exception:
            return []
        cmds: list[CommandEntry] = []
        for section in ("project", "tool.poetry"):
            scripts = data
            for key in section.split("."):
                scripts = scripts.get(key, {})
            scripts = scripts.get("scripts", {})
            for name, entry in scripts.items():
                cmd_str = entry if isinstance(entry, str) else str(entry)
                cmds.append(
                    CommandEntry(name=name, command=cmd_str, source="pyproject.toml")
                )
        return cmds

    def _parse_makefile(self, root: Path) -> list[CommandEntry]:
        makefile = root / "Makefile"
        if not makefile.exists():
            return []
        try:
            text = makefile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        targets: list[CommandEntry] = []
        for m in re.finditer(r"^([a-zA-Z][a-zA-Z0-9_-]*):", text, re.MULTILINE):
            name = m.group(1)
            targets.append(
                CommandEntry(name=name, command=f"make {name}", source="Makefile")
            )
        return targets

    def _parse_go_mod(self, root: Path) -> list[CommandEntry]:
        if not (root / "go.mod").exists():
            return []
        cmds: list[CommandEntry] = []
        if (root / "main.go").exists():
            cmds.append(CommandEntry(name="run", command="go run .", source="go.mod"))
        cmd_dir = root / "cmd"
        if cmd_dir.is_dir():
            for sub in sorted(cmd_dir.iterdir()):
                if sub.is_dir() and any(sub.glob("*.go")):
                    cmds.append(
                        CommandEntry(
                            name=sub.name,
                            command=f"go run ./cmd/{sub.name}",
                            source="go.mod",
                        )
                    )
        if not cmds:
            cmds.append(CommandEntry(name="run", command="go run .", source="go.mod"))
        return cmds

    def _parse_cargo_toml(self, root: Path) -> list[CommandEntry]:
        cargo_file = root / "Cargo.toml"
        if not cargo_file.exists():
            return []
        cmds = [
            CommandEntry(name="run", command="cargo run", source="Cargo.toml"),
            CommandEntry(name="build", command="cargo build", source="Cargo.toml"),
            CommandEntry(name="test", command="cargo test", source="Cargo.toml"),
        ]
        try:
            import tomllib

            data = tomllib.loads(cargo_file.read_text(encoding="utf-8"))
            bins = data.get("bin", [])
            for b in bins:
                if "name" in b:
                    cmds.append(
                        CommandEntry(
                            name=b["name"],
                            command=f"cargo run --bin {b['name']}",
                            source="Cargo.toml",
                        )
                    )
        except Exception:
            pass
        return cmds
