**A pre-release of FLEx Scratchpad for Windows.** It works, it is tested by hand on real FieldWorks projects, and it will still have rough edges. Please report what breaks.

FLEx Scratchpad is a notebook for FieldWorks: notes in tabs and folders that show live FLEx lexical entries and interlinear examples, read straight from your project (never written to). Highlight words in an example, put examples in tables, number them, collect them into an example collection and export that as a FLEx text.

### New in this pre-release

- **Attach files to a note.** A chip opens the file in its own program; a web page (such as a FlexText Editor listening page) previews inside the note. Pictures and videos show in the note. Files are copied into the notebook, or linked if you prefer.
- **Back up your notebook** to a OneDrive, Google Drive or Dropbox folder, or to S3-compatible storage (encryption optional, keys kept in Windows Credential Manager). It keeps old versions, shows a progress bar, backs up when you close the program, shows how much space notes and backups use, and can clean up. Settings › Backup & storage.
- **Examples stay on their lines** when you split, merge or delete lines in FLEx, and are found again by their text when a paragraph is rebuilt.
- **Playback** lights the line that is playing and follows it; the player stays in view, and a bar at the bottom of the window can always pause or stop whatever is playing.
- **Exporting a collection as a FLEx text** now writes one audio file for the text by default: each example's audio in order, with a click between examples, named like the .flextext and saved beside it (the FlexText Audio Segmenter pairs them by name). One small file per line is still a choice. Examples whose texts use different baseline writing systems become one .flextext each, with their own audio.
- Examples in a collection fold to chips; empty FLEx lines (left by Shift+Enter) are left out; **Texts used** lists the FLEx texts a note, a selection or a folder draws on.
- Fixes: one Backspace removes a whole line break; styling inside a preview no longer jumps to the top; closing the program no longer ends in an error message.

### Download

- **FLEx-Scratchpad-Setup-…exe**: the installer. Per user, no administrator rights; it adds a Start menu entry and appears in Settings › Apps. Running a newer Setup upgrades in place; your notebooks and settings are kept.
- **FLEx-Scratchpad-…-windows-portable.zip**: the same program, no installer. Unzip anywhere and run `FLEx Scratchpad.exe`.

ffmpeg (for cutting audio clips from any recording) and rclone (for backups to S3-compatible storage) are included; nothing is downloaded when the program runs.

### Needs

- Windows 10 or 11, 64-bit.
- **FieldWorks 9** on the same computer to read a FLEx project. Without it you can open a `.flextext` file or try the built-in demo.
- Microsoft Edge WebView2 Runtime (Windows 11 has it; Setup says so if this computer lacks it).

### Before you run it

The program isn't signed yet, so Windows SmartScreen may say "Windows protected your PC": choose **More info**, then **Run anyway**.

If something does not work, `FLEx Scratchpad.exe --selftest report.json` (from a command prompt in the program's folder) writes what the program can and cannot find; attach that file to an issue.
