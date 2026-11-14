# hinstall
Installation package for Herlegon tools

## Installation
### Conda environment
 `conda create -n m python=3.14`

### Python packages
`pip install -r requirements.txt`

### Tests
- FFmpeg: `python tests/test_install_packages.py`


### App installation
```sh
conda update conda
conda update --all --name base
conda create -n r python=3.14
conda activate r
python install.py
conda deactivate
conda env remove --name r
```
