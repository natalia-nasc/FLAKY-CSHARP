MAIN = main

ENGINE = -pdf

LATEXMK = latexmk $(ENGINE) -interaction=nonstopmode -halt-on-error -file-line-error

.PHONY: all pdf watch clean distclean

all: pdf

pdf:
	$(LATEXMK) $(MAIN).tex

watch:
	$(LATEXMK) -pvc $(MAIN).tex

clean:
	latexmk -c $(MAIN).tex
	rm -f *.bbl *.run.xml *.synctex.gz

distclean:
	latexmk -C $(MAIN).tex
	rm -f *.bbl *.run.xml *.synctex.gz