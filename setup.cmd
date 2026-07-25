@echo off
setlocal EnableDelayedExpansion
REM Genome Index Service - setup (Windows).
REM Asks which mode you want and where the data should live, then writes a single
REM .env that the launcher (gis.cmd) reads.
REM
REM Both container modes work on native Windows. Socket mode additionally needs
REM an absolute path (drive letter + colon): it is translated below into the
REM //<drive>/... form Docker Desktop expects when the service itself asks the
REM daemon to bind the data directory into a tool container (see
REM deploy-socket/docker-compose.yml for why that translation is needed).
REM The native mode (a plain process managed by systemd) is Linux/macOS only.

cd /d "%~dp0"

echo ==============================================
echo  Genome Index Service - setup
echo ==============================================
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo Docker was not found. Install Docker Desktop first.
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo Warning: cannot talk to Docker. Is Docker Desktop running?
  echo          Setup will continue, but nothing will start until it is.
  echo.
)

echo How should the service run?
echo.
echo   1^) dind    - one privileged container carrying its own Docker.
echo                Needs only Docker. Tool images are rebuilt after a restart.
echo                Good for a laptop or a demo. This is the usual choice here.
echo.
echo   2^) socket  - a normal container that uses Docker Desktop's daemon to run
echo                the tool containers beside it. Not privileged, tool images
echo                stay cached. It mounts the Docker socket, which gives that
echo                container root-equivalent control of Docker on this machine.
echo.
set "MODE="
set /p "CHOICE=Choose 1 or 2 [1]: "
if "%CHOICE%"=="" set "CHOICE=1"
if "%CHOICE%"=="1" set "MODE=dind"
if "%CHOICE%"=="2" set "MODE=socket"
if "%MODE%"=="" (
  echo Not a valid choice: %CHOICE%
  exit /b 1
)

REM Socket mode hands the host's Docker socket to the service container, so ask
REM for an explicit confirmation rather than letting it slip by in the menu text.
if "%MODE%"=="socket" (
  echo.
  echo Mode 'socket' mounts the Docker socket into the service container.
  echo That gives it control of Docker on this machine, which is effectively
  echo root here. Choose mode 1 instead if that is not acceptable.
  echo.
  set "CONFIRM="
  set /p "CONFIRM=Continue with socket mode? (yes/no) [yes]: "
  if "!CONFIRM!"=="" set "CONFIRM=yes"
  if /I not "!CONFIRM!"=="yes" if /I not "!CONFIRM!"=="y" (
    echo Aborted.
    exit /b 1
  )
)

if "%MODE%"=="dind" (set "DEFDATA=./data") else (set "DEFDATA=C:\genome-index-service\data")
echo.
set /p "DATA=Where should genomes and indexes be stored [%DEFDATA%]: "
if "%DATA%"=="" set "DATA=%DEFDATA%"

REM ---------------------------------------------------------------- socket --
REM The daemon in socket mode lives OUTSIDE this container (Docker Desktop's own
REM Linux VM). The compose file mounts the data directory into the service
REM container normally, but when the service later asks that same daemon to
REM bind the data directory into a tool container it spawns (bowtie2, STAR...),
REM it has to hand the daemon a path the daemon itself can resolve - a raw
REM C:\... string only works for Windows-side Docker clients (like the compose
REM invocation below), not for the Engine API calls the service makes from
REM inside a Linux container over the socket. Docker Desktop resolves those as
REM //<drive>/rest/of/path instead, so translate to that form here.
set "SIBLING="
if not "%MODE%"=="socket" goto after_sibling

echo %DATA%| findstr /r "^[A-Za-z]:[\\/]" >nul
if errorlevel 1 (
  echo.
  echo In socket mode the data path must be an absolute Windows path, such as
  echo C:\genome-index-service\data - got '%DATA%'.
  exit /b 1
)
for /f "usebackq delims=" %%S in (`powershell -NoProfile -Command "$p='%DATA%'; $drive=$p.Substring(0,1).ToLower(); $rest=($p.Substring(2) -replace '\\','/'); Write-Output ('//' + $drive + $rest)"`) do set "SIBLING=%%S"
if "%SIBLING%"=="" (
  echo.
  echo Could not translate '%DATA%' for Docker Desktop. Pick a plain absolute
  echo path such as C:\genome-index-service\data and try again.
  exit /b 1
)
echo   sibling-container mount source: %SIBLING%
:after_sibling

set /p "UPORT=Port for the user interface [8000]: "
if "%UPORT%"=="" set "UPORT=8000"
set /p "APORT=Port for the admin interface [8888]: "
if "%APORT%"=="" set "APORT=8888"
set /p "ABIND=Address for the admin interface (127.0.0.1 keeps it local) [127.0.0.1]: "
if "%ABIND%"=="" set "ABIND=127.0.0.1"
set /p "THREADS=Default CPU threads for indexing [4]: "
if "%THREADS%"=="" set "THREADS=4"

if "%UPORT%"=="%APORT%" (
  echo The two ports must differ.
  exit /b 1
)

if exist .env (
  copy /Y .env .env.bak >nul
  echo (kept a copy of the previous configuration in .env.bak^)
)

> .env echo # Genome Index Service configuration - written by setup.cmd
>> .env echo # Every mode reads this file. Re-run setup.cmd to change it, or edit by hand.
>> .env echo.
>> .env echo GIS_MODE=%MODE%
>> .env echo GIS_DATA_DIR=%DATA%
if not "%SIBLING%"=="" (
>> .env echo GIS_DATA_HOST_BIND=%SIBLING%
)
>> .env echo GIS_USER_PORT=%UPORT%
>> .env echo GIS_ADMIN_PORT=%APORT%
>> .env echo GIS_ADMIN_BIND=%ABIND%
>> .env echo GIS_USER_BIND=0.0.0.0
>> .env echo INDEX_THREADS=%THREADS%
>> .env echo DNA_PREFERENCE=primary_assembly,toplevel
>> .env echo HOST_UID=
>> .env echo HOST_GID=

echo.
echo ==============================================
echo  Configured: mode '%MODE%'
echo ==============================================
echo   data directory : %DATA%
if not "%SIBLING%"=="" echo   sibling mount  : %SIBLING%  ^(what the daemon uses for tool containers^)
echo   user interface : http://localhost:%UPORT%
echo   admin interface: http://%ABIND%:%APORT%
echo   written to     : .env
echo.
echo Next:
echo     gis.cmd start
echo     gis.cmd status
echo     gis.cmd logs
echo     gis.cmd stop
echo.
endlocal
