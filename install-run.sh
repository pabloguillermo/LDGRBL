#!/usr/bin/env bash
# Prepara o ambiente (venv + dependências) na primeira execução e abre o LDGRBL.
# Uso: ./install-run.sh        (pode ser rodado quantas vezes quiser)
set -e
cd "$(dirname "$0")"

if ! python3 -c "import venv, ensurepip" 2>/dev/null; then
    echo "Faltam o venv/pip do Python. Em Debian/Ubuntu:"
    echo "  sudo apt install python3-venv python3-pip"
    exit 1
fi

if [ ! -x venv/bin/python ]; then
    echo ">> Criando ambiente virtual em ./venv"
    # Se o wxPython/numpy/Pillow do sistema (apt) existirem, reaproveita-os:
    # compilar o wxPython via pip leva muito tempo e exige várias libs.
    python3 -m venv --system-site-packages venv
fi

# Só reinstala quando o requirements.txt mudou.
STAMP=venv/.requirements.stamp
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
    echo ">> Instalando dependências"
    # Descarta o pin 'numpy<=1.26.4' se já houver um numpy utilizável no sistema
    # (o pin impede instalar em Pythons novos e o app funciona com numpy 2.x).
    REQ=$(mktemp)
    if venv/bin/python -c "import numpy" 2>/dev/null; then
        grep -vi '^numpy' requirements.txt > "$REQ"
    else
        cp requirements.txt "$REQ"
    fi
    # wxPython: se já existir (apt), não tenta compilar via pip.
    if venv/bin/python -c "import wx" 2>/dev/null; then
        sed -i '/^wxPython/Id' "$REQ"
    fi
    if ! venv/bin/python -m pip install -r "$REQ"; then
        rm -f "$REQ"
        echo "Falha ao instalar dependências. Em Debian/Ubuntu, tente:"
        echo "  sudo apt install python3-wxgtk4.0 python3-numpy python3-pil libgtk-3-dev libpython3-dev"
        exit 1
    fi
    rm -f "$REQ"
    touch "$STAMP"
fi

exec venv/bin/python ldgrbl.py "$@"
