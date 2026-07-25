@echo off
REM Genome Index Service - delete the data folder.
REM
REM Genomes and indexes are written by containers running as root, so if a run
REM predates the permission fix Windows may refuse to delete them. This removes
REM the contents from inside a container (as root), which always works, then
REM removes the empty folder.

echo.
echo === Delete .\data (genomes, indexes, tools, jobs, requests) ===
echo.
set /p CONFIRM="This deletes ALL downloaded genomes and built indexes. Type YES to continue: "
if /I not "%CONFIRM%"=="YES" (
  echo Aborted.
  exit /b 1
)

echo.
echo Stopping the service...
docker compose down --remove-orphans

echo.
echo Removing contents from inside a container...
docker run --rm -v "%CD%\data:/target" alpine:3.20 sh -c "rm -rf /target/* /target/.[!.]* 2>/dev/null; exit 0"

echo.
echo Removing the empty folder...
rmdir /S /Q data 2>nul

if exist data (
  echo.
  echo The folder is still there. Try again, or remove it from an elevated prompt.
) else (
  echo.
  echo Done: .\data removed.
)
