; installer.nsi -- FLEx Scratchpad for Windows: the Setup .exe most people download.
;
; What it does: copy the program folder (PyInstaller's onedir build, with ffmpeg in ffmpeg\) into
; %LOCALAPPDATA%\Programs\FLEx Scratchpad, add a Start menu shortcut (and, if ticked, one on the
; desktop), and register an uninstaller under Settings > Apps. Everything is per user: no
; administrator rights, nothing outside the user's own profile. Notebooks and settings are never
; touched -- they live in Documents and %APPDATA%, and uninstalling leaves them where they are.
;
; UPGRADING is the same run. The program must not be running (checked first; a silent run stops
; with exit code 2 instead of waiting on a box nobody sees), and the old program files are removed
; before the new ones are copied, so no file of an older build is left to mix with the new one.
; Only the folders this installer itself writes are ever removed -- never the install folder
; wholesale, which someone may have pointed at a folder with other things in it.
;
; Built in CI (.github/workflows/windows-package.yml):
;   makensis /DVERSION=0.1.0-beta.1 /DSRC=<dist\FLEx Scratchpad> /DOUT=<Setup.exe> /DICON=<.ico> build\installer.nsi
; Unsigned: SmartScreen says "unknown publisher" until it is.

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef SRC
  !define SRC "dist\FLEx Scratchpad"
!endif
!ifndef OUT
  !define OUT "FLEx-Scratchpad-Setup.exe"
!endif
!ifndef ICON
  !define ICON "..\flex_scratchpad\ui\img\flex-scratchpad.ico"
!endif

!define APP "FLEx Scratchpad"
!define EXE "FLEx Scratchpad.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\FLEx Scratchpad"

!include "MUI2.nsh"

Name "${APP}"
OutFile "${OUT}"
Unicode true
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "${UNINST_KEY}" "InstallLocation"
SetCompressor /SOLID lzma
BrandingText "${APP} ${VERSION}"

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "${APP} ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "This installs FLEx Scratchpad, a notebook for FieldWorks: notes in folders that show live FLEx entries and interlinear examples, read straight from your project.$\r$\n$\r$\nIt installs for your user account only and needs no administrator rights. An earlier version is replaced; your notebooks and settings are kept.$\r$\n$\r$\nThis is a pre-release. Close FLEx Scratchpad before continuing."
!define MUI_FINISHPAGE_TITLE "Installed"
!define MUI_FINISHPAGE_TEXT "FLEx Scratchpad is in the Start menu.$\r$\n$\r$\nTo read a FLEx project it needs FieldWorks 9 on this computer. Without it you can still open a .flextext file or try the built-in demo.$\r$\n$\r$\nTo remove it: Settings > Apps > FLEx Scratchpad > Uninstall. Your notebooks stay."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Start FLEx Scratchpad"
!define MUI_FINISHPAGE_SHOWREADME ""
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Add a shortcut on the desktop"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION DesktopShortcut
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

; Is FLEx Scratchpad running? Leaves "1" or "0" on the stack. tasklist's words are localized, the
; image name is not, so find looks for that.
!macro APP_FUNCTIONS un
Function ${un}AppIsRunning
  nsExec::ExecToStack '"$SYSDIR\cmd.exe" /c tasklist /FI "IMAGENAME eq ${EXE}" /NH | find /I "${EXE}"'
  Pop $0          ; exit code: 0 when find saw it
  Pop $1
  StrCmp $0 "0" running
  Push "0"
  Return
  running:
  Push "1"
FunctionEnd

Function ${un}WaitForApp
  check:
    Call ${un}AppIsRunning
    Pop $0
    StrCmp $0 "0" closed
    MessageBox MB_ICONEXCLAMATION|MB_RETRYCANCEL "FLEx Scratchpad is running. Close its window, then click Retry." /SD IDCANCEL IDRETRY check
    Push "cancel"
    Return
  closed:
    Push "ok"
FunctionEnd
!macroend
!insertmacro APP_FUNCTIONS ""
!insertmacro APP_FUNCTIONS "un."

Function .onInit
  Call WaitForApp
  Pop $0
  StrCmp $0 "cancel" 0 +3
    SetErrorLevel 2
    Abort
FunctionEnd

Function un.onInit
  Call un.WaitForApp
  Pop $0
  StrCmp $0 "cancel" 0 +3
    SetErrorLevel 2
    Abort
FunctionEnd

; The window is Microsoft's WebView2 (Edge). Windows 11 always has its runtime and most Windows 10
; machines do; when neither the machine-wide nor the per-user runtime is registered, say where to
; get it rather than leave the program unable to open its window. A warning only: the install goes on.
!define WV2_GUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
Function CheckWebView2
  ReadRegStr $0 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WV2_GUID}" "pv"
  StrCmp $0 "" 0 found
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WV2_GUID}" "pv"
  StrCmp $0 "" 0 found
  ReadRegStr $0 HKCU "Software\Microsoft\EdgeUpdate\Clients\${WV2_GUID}" "pv"
  StrCmp $0 "" 0 found
  MessageBox MB_ICONINFORMATION|MB_OK "FLEx Scratchpad draws its window with Microsoft Edge WebView2, which this computer does not seem to have.$\r$\n$\r$\nIf the program does not open, install the WebView2 Runtime (free, from Microsoft): https://go.microsoft.com/fwlink/p/?LinkId=2124703" /SD IDOK
  found:
FunctionEnd

Function DesktopShortcut
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${EXE}"
FunctionEnd

Section "FLEx Scratchpad"
  SetOutPath "$INSTDIR"
  ; an upgrade: the previous build's program files go first (only what this installer wrote)
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\ffmpeg"
  Delete "$INSTDIR\${EXE}"
  SetOverwrite on
  File /r "${SRC}\*.*"
  ; a mark of the web on the downloaded Setup is not carried to these files, but an older copy
  ; that was unzipped by hand may carry one on the program
  System::Call 'kernel32::DeleteFileW(w "$INSTDIR\${EXE}:Zone.Identifier")'

  Call CheckWebView2
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\${EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" '"$INSTDIR\${EXE}",0'
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Seth Johnston"
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout" "https://github.com/rulingAnts/flex-scratchpad"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\ffmpeg"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"                      ; only when nothing else is in it
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  DeleteRegKey HKCU "${UNINST_KEY}"
  ; the flexscratchpad:// links the program registered for this user at its first start
  DeleteRegKey HKCU "Software\Classes\flexscratchpad"
SectionEnd
