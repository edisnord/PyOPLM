import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pyoplm",
    version="0.6",
    author="Nold, edisnord",
    author_email="nold@gnu.one, edisnord@gmail.com",
    description="Tool To Manage Open-PS2-Loader USB-Drives & Games",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/edisnord/pyoplm",
    packages=setuptools.find_packages(),
    include_package_data=True,
    install_requires=[
        "pillow==9.4.0",
        "beautifulsoup4==4.12.2",
        "lxml"
    ],
    package_data={"": ["pyoplm/lib/linux64/bchunk/*"],
                  "": ["pyoplm/lib/linux64/binmerge/*"],
                  "": ["pyoplm/lib/linux64/cue2pops/*"]},
    entry_points={
        'console_scripts': [
            'pyoplm= pyoplm:main',
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: POSIX :: Linux",
	"Environment :: Console"
    ],
)
