# RelayCache PyPI Publishing Instructions

## Preparation for Publishing

### 1. Install Required Tools

```bash
pip install build twine
```

### 2. Run Tests

```bash
python -m pytest tests/ -v
```

### 3. Build Package

```bash
python -m build
```

This command will create files in the `dist/` folder:
- `relaycache-0.1.0.tar.gz` (source code)
- `relaycache-0.1.0-py3-none-any.whl` (wheel package)

### 4. Check Package

```bash
python -m twine check dist/*
```

## Publishing

### Test PyPI (recommended for first publication)

1. Register at https://test.pypi.org/
2. Upload package:
```bash
python -m twine upload --repository testpypi dist/*
```

3. Install and test:
```bash
pip install --index-url https://test.pypi.org/simple/ relaycache
```

### Main PyPI

1. Register at https://pypi.org/
2. Upload package:
```bash
python -m twine upload dist/*
```

## Using publish.py Script

For convenience, use our automated script:

```bash
# Tests only
python publish.py test

# Build package
python publish.py build

# Check package
python publish.py check

# Publish to Test PyPI
python publish.py testpypi

# Publish to PyPI
python publish.py publish
```

## GitHub Actions Setup (optional)

Create `.github/workflows/publish.yml` for automatic publishing when creating a tag:

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - 'v*'

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install build twine
    - name: Run tests
      run: python -m pytest tests/
    - name: Build package
      run: python -m build
    - name: Publish to PyPI
      env:
        TWINE_USERNAME: __token__
        TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
      run: twine upload dist/*
```

## Important Notes

1. **Versioning**: Update version in `pyproject.toml` before each publication
2. **Testing**: Always run tests before publishing
3. **Security**: Use API tokens instead of passwords
4. **Documentation**: Update README.md when adding new features
