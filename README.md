# LDGRBL

🇧🇷 [Português](#português) · 🇬🇧 [English](#english)

---

## Português

**LDGRBL** é um fork do [MeerK40t](https://github.com/meerk40t/meerk40t) **versão 0.9.8100**, adaptado para gravadores a laser e máquinas CNC com **GRBL** (Acmer, Atomstack, Creality, Ortur, Longer e outros).

### O que muda em relação ao MeerK40t

- Nome, título da janela e ícone próprios (LDGRBL, ícone do gravador com dragão).
- **Reset e home automáticos ao conectar:** ao conectar, o programa envia o reset ao dispositivo e, assim que o GRBL confirma (mensagem de boas-vindas), faz o home físico (`$H`, ou `G28` se não houver endstops). Dá para desligar em *Configurações do dispositivo → Validation → "Reset and home on connect"*.
- Ajustes no fluxo de trabalho do GRBL (veja o histórico do git).
- O restante (Lihuiyu/K40, galvo JCZ, console, operações, etc.) é herdado do MeerK40t.

> Por compatibilidade, o diretório de configuração continua sendo `~/.config/MeerK40t` (Linux). Assim, as configurações de quem já usava o MeerK40t são mantidas.

### Download (Linux)

Baixe o **AppImage** pronto na página de [Releases](https://github.com/pabloguillermo/LDGRBL/releases/latest):

```bash
chmod +x LDGRBL.AppImage
./LDGRBL.AppImage
```

### Rodando a partir do código-fonte

Requisitos: Python 3.8 ou superior (testado com Python 3.13 em Debian 13) e, no Linux, as bibliotecas de desenvolvimento do GTK.

```bash
# Debian/Ubuntu: dependências do sistema
sudo apt install python3-venv python3-pip libgtk-3-dev libpython3-dev

# 1. Clonar
git clone https://github.com/pabloguillermo/LDGRBL.git
cd LDGRBL

# 2. Ambiente virtual e dependências
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Executar
python meerk40t.py
```

Opcionais (mais velocidade e recursos): veja `requirements-optional-linux.txt`, `requirements-optional-win.txt` e `linux.txt`.

> Dica: para testar sem mexer nas suas configurações reais, rode com um `HOME` temporário:
> `HOME=$(mktemp -d) python meerk40t.py`

### Modificando e contribuindo

1. Crie uma branch: `git checkout -b minha-alteracao`.
2. Código do GRBL: [meerk40t/grbl/](meerk40t/grbl/) (`controller.py`, `driver.py`, `device.py`, `gui/`).
3. Interface: [meerk40t/gui/](meerk40t/gui/). Textos traduzíveis ficam em [locale/](locale/).
4. Rode os testes antes de enviar:
   ```bash
   python -m unittest discover -s test
   ```
5. Faça commit e abra um Pull Request.

### Gerando um AppImage (Linux)

O build usa o PyInstaller em modo *onedir*, depois empacota com o `appimagetool`:

```bash
pip install pyinstaller
mv meerk40t.py mk40t.py     # o PyInstaller se confunde com o pacote meerk40t
pyinstaller .github/workflows/linux/meerk40t.spec   # ou seu próprio .spec
mv mk40t.py meerk40t.py
# monte um AppDir (AppRun, .desktop, ícone, usr/bin/LDGRBL) e rode:
ARCH=x86_64 appimagetool MeuAppDir LDGRBL.AppImage
```

Inclua no build a pasta `locale/` e o arquivo `meerk40t/gui/ldgrbl.png`, que não são código Python.

### Créditos e agradecimentos

- **MeerK40t** — este projeto é baseado no MeerK40t **0.9.8100**, criado por **David Olsen (Tatarize)** e pela comunidade MeerK40t. Nossa gratidão a todos que contribuem para esse trabalho extraordinário.
  - Repositório: <https://github.com/meerk40t/meerk40t>
  - Wiki: <https://github.com/meerk40t/meerk40t/wiki>
  - Histórico de versões: <https://github.com/meerk40t/meerk40t/wiki/History:-Major-Version-History,-Changes,-and-Reasons>
- **Anthropic e Claude Code** — as modificações do LDGRBL só foram possíveis graças à [Anthropic](https://www.anthropic.com) e ao [Claude Code](https://claude.com/claude-code), que ajudaram no desenvolvimento.

### Licença

Distribuído sob a **Licença MIT**, a mesma do MeerK40t. Veja [LICENSE](LICENSE); o aviso de copyright original (© 2021 meerk40t) deve ser mantido.

---

## English

**LDGRBL** is a fork of [MeerK40t](https://github.com/meerk40t/meerk40t) **version 0.9.8100**, adapted for **GRBL** laser engravers and CNC machines (Acmer, Atomstack, Creality, Ortur, Longer and others).

### What differs from MeerK40t

- Own name, window title and icon (LDGRBL, laser engraver with dragon).
- **Automatic reset and home on connect:** on connection the app sends a reset to the device and, once GRBL confirms it (welcome message), performs a physical home (`$H`, or `G28` without endstops). Can be disabled under *Device settings → Validation → "Reset and home on connect"*.
- GRBL workflow fixes (see git history).
- Everything else (Lihuiyu/K40, JCZ galvo, console, operations, …) is inherited from MeerK40t.

> For compatibility, the settings directory is still `~/.config/MeerK40t` (Linux), so existing MeerK40t settings are kept.

### Download (Linux)

Get the ready-made **AppImage** from the [Releases](https://github.com/pabloguillermo/LDGRBL/releases/latest) page, then `chmod +x LDGRBL.AppImage && ./LDGRBL.AppImage`.

### Running from source

Requirements: Python 3.8+ (tested with Python 3.13 on Debian 13) and, on Linux, the GTK development libraries.

```bash
sudo apt install python3-venv python3-pip libgtk-3-dev libpython3-dev   # Debian/Ubuntu

git clone https://github.com/pabloguillermo/LDGRBL.git
cd LDGRBL
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python meerk40t.py
```

Tip: to avoid touching your real settings, run with a throwaway home: `HOME=$(mktemp -d) python meerk40t.py`.

### Hacking and contributing

1. `git checkout -b my-change`
2. GRBL code lives in [meerk40t/grbl/](meerk40t/grbl/); the GUI in [meerk40t/gui/](meerk40t/gui/); translations in [locale/](locale/).
3. Run the tests: `python -m unittest discover -s test`
4. Commit and open a Pull Request.

### Building an AppImage (Linux)

Build a PyInstaller *onedir* bundle (include `locale/` and `meerk40t/gui/ldgrbl.png` as data files), put it in an AppDir (`AppRun`, `.desktop`, icon, `usr/bin/LDGRBL`) and run `appimagetool`.

### Credits

- **MeerK40t** — based on MeerK40t **0.9.8100** by **David Olsen (Tatarize)** and the MeerK40t community. Many thanks to everyone behind this work.
  - Repository: <https://github.com/meerk40t/meerk40t>
  - Wiki: <https://github.com/meerk40t/meerk40t/wiki>
- **Anthropic and Claude Code** — this work was also made possible thanks to [Anthropic](https://www.anthropic.com) and [Claude Code](https://claude.com/claude-code).

### License

Released under the **MIT License**, same as MeerK40t. See [LICENSE](LICENSE); the original copyright notice (© 2021 meerk40t) must be kept.
