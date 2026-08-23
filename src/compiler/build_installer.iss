[Setup]
; Базовые настройки приложения
AppName=CUTTER MAKER
AppVersion=1.3
AppPublisher=Твоя Компания
AppPublisherURL=https://твоя-ссылка.com

; Устанавливаем в профиль пользователя (AppData\Local), чтобы избежать проблем с правами Администратора при сохранении баз данных
DefaultDirName={localappdata}\CutterMaker
DefaultGroupName=CUTTER MAKER

; Куда сохранить готовый инсталлятор и как его назвать
OutputDir=.\
OutputBaseFilename=Install_CutterMaker_v1.3

; Максимальное сжатие (чтобы инсталлятор весил меньше)
Compression=lzma2/ultra64
SolidCompression=yes

; Права пользователя (без запроса пароля админа)
PrivilegesRequired=lowest

; Иконка установщика (встроенная стандартная)
SetupIconFile=compiler:SetupClassicIcon.ico
UninstallDisplayIcon={app}\CutterMaker.exe

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на Рабочем столе"; GroupDescription: "Дополнительные значки:"; Flags: unchecked

[Files]
; Берем сам экзешник напрямую из папки dist (куда его кладет PyInstaller)
Source: "dist\CutterMaker.exe"; DestDir: "{app}"; Flags: ignoreversion

; Берем движки и базы напрямую из корня проекта и кладем в соответствующие папки при установке
Source: "inkscape_engine\*"; DestDir: "{app}\inkscape_engine"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "ghostscript_engine\*"; DestDir: "{app}\ghostscript_engine"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "data\*"; DestDir: "{app}\data"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Ярлык в меню Пуск
Name: "{group}\CUTTER MAKER"; Filename: "{app}\CutterMaker.exe"
; Ярлык на Рабочий стол
Name: "{autodesktop}\CUTTER MAKER"; Filename: "{app}\CutterMaker.exe"; Tasks: desktopicon

[Run]
; Запуск программы после установки
Filename: "{app}\CutterMaker.exe"; Description: "Запустить CUTTER MAKER"; Flags: nowait postinstall skipifsilent