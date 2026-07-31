from pathlib import Path


def test_static_demo_files_exist():
    root = Path(__file__).resolve().parents[1]
    expected = [
        'index.html', 'login.html', 'app.html', 'privacidad.html', 'terminos.html',
        '404.html', 'manifest.webmanifest', 'sw.js', 'assets/styles.css',
        'assets/enhancements.css', 'assets/app.js', 'assets/enhancements.js',
    ]
    missing = [name for name in expected if not (root / name).exists()]
    assert not missing, f'Faltan archivos: {missing}'
