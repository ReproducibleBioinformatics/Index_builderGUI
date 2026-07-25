@echo off
setlocal EnableDelayedExpansion
REM Genome Index Service - one launcher for both container modes (Windows).
REM Reads .env (written by setup.cmd) so you never have to remember which
REM compose file applies.
REM
REM   gis.cmd start | stop | restart | status | logs | rebuild | urls | config

cd /d "%~dp0"

if not exist .env (
  echo No .env found. Run setup.cmd first.
  exit /b 1
)

for /f "usebackq tokens=1,* delims==" %%A in (`findstr /v "^#" .env ^| findstr "="`) do set "%%A=%%B"

if "%GIS_MODE%"=="" set "GIS_MODE=dind"
if "%GIS_USER_PORT%"=="" set "GIS_USER_PORT=8000"
if "%GIS_ADMIN_PORT%"=="" set "GIS_ADMIN_PORT=8888"
if "%GIS_ADMIN_BIND%"=="" set "GIS_ADMIN_BIND=127.0.0.1"

if /I "%GIS_MODE%"=="dind"   set "CF=docker-compose.yml"
if /I "%GIS_MODE%"=="socket" set "CF=deploy-socket\docker-compose.yml"
if /I "%GIS_MODE%"=="native" (
  echo Mode 'native' is Linux/macOS only. Re-run setup.cmd and pick 1 or 2.
  exit /b 1
)

set "CMD=%~1"
if "%CMD%"=="" set "CMD=help"

if /I "%CMD%"=="start"   goto start
if /I "%CMD%"=="rebuild" goto rebuild
if /I "%CMD%"=="stop"    goto stop
if /I "%CMD%"=="restart" goto restart
if /I "%CMD%"=="status"  goto status
if /I "%CMD%"=="logs"    goto logs
if /I "%CMD%"=="urls"    goto urls
if /I "%CMD%"=="config"  goto config
goto help

:start
echo --^> Starting in '%GIS_MODE%' mode (data: %GIS_DATA_DIR%)
docker compose -f "%CF%" up --build -d
if errorlevel 1 exit /b 1
echo.
goto urls

:rebuild
echo --^> Rebuilding in '%GIS_MODE%' mode
docker compose -f "%CF%" up --build --force-recreate -d
if errorlevel 1 exit /b 1
echo.
goto urls

:stop
docker compose -f "%CF%" down
goto end

:restart
call "%~f0" stop
call "%~f0" start
goto end

:status
echo mode: %GIS_MODE%
echo data: %GIS_DATA_DIR%
call :printurls
echo.
docker compose -f "%CF%" ps
goto end

:logs
docker compose -f "%CF%" logs -f
goto end

:urls
call :printurls
echo.
echo Logs: gis.cmd logs      Stop: gis.cmd stop
goto end

:config
echo Current configuration (.env):
echo.
findstr /v "^#" .env | findstr "="
goto end

:help
echo Usage: gis.cmd start ^| stop ^| restart ^| status ^| logs ^| rebuild ^| urls ^| config
echo.
echo Current mode: %GIS_MODE%
goto end

:printurls
echo   user interface : http://localhost:%GIS_USER_PORT%
echo   admin interface: http://%GIS_ADMIN_BIND%:%GIS_ADMIN_PORT%
exit /b 0

:end
endlocal
