echo Building Meerk40t executable v.0.1
echo This script assumes that you have a working python environment where you can run meerk40t from source
echo Making sure plugins are loaded
move meerk40t\external_plugins.py meerk40t\external_plugins.unused
move meerk40t\external_plugins_build.py meerk40t\external_plugins.py

echo Renaming main file for the build
pyinstaller .github\workflows\win\meerk40t.spec
echo Moving files back to their original places
move meerk40t\external_plugins.py meerk40t\external_plugins_build.py
move meerk40t\external_plugins.unused meerk40t\external_plugins.py
