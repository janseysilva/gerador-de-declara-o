# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# Leitor de notas fiscais (OCR): bibliotecas + os 2 modelos de ../modelos_ocr (vão para dentro do .exe)
_dados, _bins, _ocultos = [], [], []
for _pacote in ('rapidocr', 'onnxruntime'):
    _d, _b, _h = collect_all(_pacote)
    _dados += _d
    _bins += _b
    _ocultos += _h
# O pacote rapidocr traz modelos proprios (31 MB) que o programa NAO usa: ele usa os de ../modelos_ocr.
_dados = [d for d in _dados if not d[0].replace('\\', '/').lower().endswith('.onnx')]


a = Analysis(
    ['declaracoes_escolares.py'],
    pathex=[],
    binaries=_bins,
    datas=[('icone_declaracoes.ico', '.'), ('catalogo_base.json', '.'), ('catalogo_federal.json', '.'), ('modelos_ocr', 'modelos_ocr')] + _dados,
    hiddenimports=['reportlab.graphics.barcode.common', 'docx', 'frequencia_gier', 'gier_auto', 'gier_online', 'pareceres_gier', 'registro', 'estoque', 'tela_estoque', 'leitor_nota', 'catalogo', 'acesso', 'atualizacao', 'tela_login', 'tela_usuarios', 'pypdfium2', 'pypdfium2_raw', 'pdfplumber', 'cv2', 'shapely', 'pyclipper', 'omegaconf', 'yaml', 'tqdm', 'requests'] + _ocultos,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# A biblioteca de video do OpenCV (31 MB) nunca e usada: o programa so le imagens de PDF.
a.binaries = [b for b in a.binaries if 'opencv_videoio_ffmpeg' not in b[0]]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DeclaracoesEscolares',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icone_declaracoes.ico'],
)
