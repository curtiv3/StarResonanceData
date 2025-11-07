# Scripts

## Drop chance generator

Run the following command from the repository root to build the CSV reports:

```bash
python scripts/build_drop_chance.py
```

The generated files are placed in the `drop_chance/` directory. The CSV outputs are ignored by Git (only a `.gitkeep` placeholder is tracked), so you may re-run the command locally whenever you need fresh data without committing the large generated artifacts.
