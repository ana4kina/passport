# Постобработка OCR паспорта РФ

```bash
python postprocess.py data/test_predictions.jsonl answers.jsonl
```

Только стандартная библиотека Python 3.9+, CPU, без интернета.

Проверка на train:

```bash
python postprocess.py data/train_predictions.jsonl train_answers.jsonl
python evaluate.py train_answers.jsonl data/train_labels.jsonl
```

`evaluate.py` не проверяет действительность паспорта на 01.10.2026 — это делает `postprocess.py`.

Подробности — в [REPORT.md](REPORT.md).
