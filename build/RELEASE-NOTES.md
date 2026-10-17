**A pre-release of FLEx Scratchpad for Windows.** It works, it is tested by hand on real FieldWorks projects, and it will still have rough edges. Please report what breaks.

FLEx Scratchpad is a notebook for FieldWorks: notes in tabs and folders that show live FLEx lexical entries and interlinear examples, read straight from your project (never written to). Highlight words in an example, put examples in tables, number them, collect them into an example collection and export that as a FLEx text.

### Download

- **FLEx-Scratchpad-Setup-…exe**: the installer. Per user, no administrator rights; it adds a Start menu entry and appears in Settings › Apps. Running a newer Setup upgrades in place; your notebooks and settings are kept.
- **FLEx-Scratchpad-…-windows-portable.zip**: the same program, no installer. Unzip anywhere and run `FLEx Scratchpad.exe`.

ffmpeg (for cutting audio clips from any recording) is included; nothing is downloaded when the program runs.

### Needs

- Windows 10 or 11, 64-bit.
- **FieldWorks 9** on the same computer to read a FLEx project. Without it you can open a `.flextext` file or try the built-in demo.
- Microsoft Edge WebView2 Runtime (Windows 11 has it; Setup says so if this computer lacks it).

### Before you run it

The program isn't signed yet, so Windows SmartScreen may say "Windows protected your PC": choose **More info**, then **Run anyway**.

If something does not work, `FLEx Scratchpad.exe --selftest report.json` (from a command prompt in the program's folder) writes what the program can and cannot find; attach that file to an issue.
