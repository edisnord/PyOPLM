default: build

build:
	uv build

install:
	uv pip install --force dist/*.whl

clean:
	rm -rf dist build pyoplm.egg-info/

release:
	uv publish
