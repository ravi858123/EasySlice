<img src="icon.png" width="120" align="right">

# EasySlice

Simpele slicer voor Windows. Opent STL, OBJ, PLY, OFF, 3MF, GLB/GLTF en DAE en maakt G-code (Marlin-stijl).

- **Schalen**: percentage per as of gelijkmatig, "Pas op bouwplaat", rotatie Z
- **Supports**: geen / alleen vanaf bouwplaat / overal, overhanghoek, afstand en tussenruimte
- **Snel ↔ detail**: voorinstellingen 0.30 / 0.20 / 0.10 mm, plus alles handmatig aan te passen
- Hechting: skirt of brim, laagvoorbeeld met schuifbalk, geschatte printtijd en filamentverbruik

## EXE bouwen op GitHub
1. Maak een repo en upload alle bestanden (inclusief de map `.github`).
2. Ga naar **Actions → Build Windows EXE → Run workflow**.
3. Download na ±3 minuten het artifact **EasySlice-win64**: dat is één .zip met `EasySlice.exe`.
4. Wil je een Release? Maak een tag, bijv. `v1.0`: dan komt de .zip ook onder Releases.

Lokaal draaien: `pip install -r requirements.txt` en `python app.py`.

Let op: STEP/IGES worden niet ondersteund (exporteer die eerst naar STL/3MF). Test eerst met een klein model en controleer de G-code (temperaturen, bouwplaat) voor je print.
