PYTHON ?= python3
SJASMPLUS ?= sjasmplus

.PHONY: all test clean
all:
	$(PYTHON) tools/build.py --assembler $(SJASMPLUS)
test: all
	$(PYTHON) tools/verify.py
clean:
	rm -rf build
