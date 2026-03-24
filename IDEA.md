## 介绍
这个项目，我想实现的是通过im软件实现控制claude code来给我干活的工具。主要由一个主控agent，操作claude code 会话管理器和一些工具，来操作claude code来开发我项目(主要是传达我的指令)


## 功能点

### 消息渠道
- 支持多渠道
- 设计完备的消息渠道层，各个渠道写自己的兼容层即可
- 同时只支持启动一种渠道(防止多平台消息冲突)

### 消息
- agent 消费消息按照串行执行
- 消息记录

### agent
- 实现agent loop(不派生子agent，只做中央调度)
- 实现长期记忆、临时记忆、工作记忆
- 支持调用工具
- 默认读取人设提示词
- 支持自动压缩会话，总结，存储记忆


### 项目管理
claude code 会话会基于项目的
可以设置当前项目，所有的开发指令都会实际的指向指定的项目的claude code会话
可以设置当前项目(默认的开发指令之类的，定向类的都是指向默认)
- 创建
- 列出
- 切换
- 项目关联的session(claude code)
- 配置

### agent 工具
工具主要用来控制项目执行命令
- 项目管理类
- 消息发送类
- 命令执行类(安全边界)
- 服务启动类(项目编写完后，用于启动服务(派发子任务))
- 工具安装类
  - skill
  - mcp


### claude code 会话
使用Claude agent sdk进行claude code会话管理，所有的claude会话都是基于项目的，运行workspace都在项目目录中。
支持claude code的所有原生功能，并且支持加载全局和项目的.claude文件系统
通过claude agent sdk进行Claude code会话的交互
支持Claude code 启动，执行完毕，异常等事件的监听，去主动送入消息队列，由调度主agent处理消息
项目支持会话记录(可以尝试在项目文件夹中创建配置文件，用于持久化一些项目的信息)

### 要求
- 项目结构要清晰
- 使用python语言
- 使用uv包管理
- 使用uv venv创建本地虚拟环境
- 主agent框架使用pydantic-ai: https://ai.pydantic.dev
- claude agent sdk使用claude agent sdk python: ./docs/claude-agent-sdk.md
