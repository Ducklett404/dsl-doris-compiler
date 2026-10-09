@echo off
setlocal
set "PROJECT_DIR=%~dp0"
set "LOCAL_MAVEN=%PROJECT_DIR%.tools\apache-maven-3.9.16\bin\mvn.cmd"
if exist "%LOCAL_MAVEN%" goto local_maven
where.exe mvn.cmd >nul 2>nul
if errorlevel 1 goto missing_maven
call mvn.cmd %*
exit /b %errorlevel%

:local_maven
call "%LOCAL_MAVEN%" "-Dmaven.repo.local=%PROJECT_DIR%.mvn-cache" %*
exit /b %errorlevel%

:missing_maven
echo Maven not found. Install Maven 3.9+ or prepare .tools\apache-maven-3.9.16. 1>&2
exit /b 1
