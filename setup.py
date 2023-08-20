"""
This is a setup.py script generated by py2applet

Usage:
    python setup.py py2app
"""

from setuptools import setup

APP = ['main.py']
DATA_FILES = [("data", ["data/yahoo", "data/draft_ids.json", "data/settings", "data/settings.json", "data/clay"])]
OPTIONS = {'plist': {'CFBundleDisplayName': 'Weez Draftboard', 'CFBundleName': 'Weez Draftboard'},
           'includes': ['yahoo_oauth',
                        'yahoo_fantasy_api',
                        'pathlib.Path',
                        'json',
                        'os',
                        'pandas',
                        'datetime.datetime',
                        'bs4',
                        'requests',
                        'time',
                        're',
                        'pdb',
                        'camelot-py',
                        'tabula']}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
