# CoreInsight Miner

本目录是 LocalToolkit 的本地阉割版：单 EXE、无定时、无规则匹配，只把 WeLink/Outlook 内容导出到 D 盘，并按需调用内置单 Prompt 模型生成经验 Markdown。

## 运行

在仓库根目录执行：

```powershell
python -m miner
```

Windows 需要 WebView2 Runtime 和 Outlook（邮件功能）以及 `welink-cli`（聊天记录功能）。

## 打包

执行 `miner\build.bat`，输出 `dist\CoreInsightMiner.exe`。

## 文件布局

```text
D:\CoreInsight\miner\
  邮件\标题.md
  邮件\标题.experience.md
  聊天记录\群名_开始_结束.md
  聊天记录\群名_开始_结束.experience.md
```

每个 Markdown 旁边还会有一个同名 `.json` 元数据文件，记录邮件 ID、消息 ID、时间范围等机器使用信息。它不是给用户编辑的，用于结果页重新提取和排查来源。
