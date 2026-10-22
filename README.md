# LDGRBL

**LDGRBL** is a modified build and fork based on [MeerK40t](https://github.com/meerk40t/meerk40t) (v0.9.8100), focused on optimizations, driver tweaks, and seamless integration for **GRBL-based** laser engravers and CNC machines (such as Acmer, Atomstack, Creality, Ortur, Longer, and others).

---

## 🚀 Key Features

* **Built on MeerK40t 0.9 Core:** Leverages a lightweight, robust, and open-source Python architecture.
* **Optimized for GRBL:** Enhanced workflow, state management, alarm handling, and specific command protocols for GRBL controllers.
* **Highly Extensible Interface:** Modular AUI-based GUI built with `wxPython`, allowing customizable layouts, panes, and tools.
* **Advanced CLI & Console:** Powerful internal console system for process automation and scriptable control via terminal.

---

## 🛠 Supported Devices

* **GRBL Controllers** (Acmer S1, Atomstack, Creality, Longer, Ortur, generic Arduino/ESP32 GRBL boards)
* **Lihuiyu M2/M3-Nano** (K40 Lasers) *(Inherited core support)*
* **Ezcad2-compatible JCZ controllers** (Galvo Lasers) *(Inherited core support)*

---

## 💻 Installation & Running from Source

Ensure you have **Python 3.8+** installed on your system (Linux, macOS, or Windows).

### 1. Clone the repository
```bash
git clone https://github.com/pabloguillermo/LDGRBL.git
cd LDGRBL
```
