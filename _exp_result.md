# Exp44 Result

- **commit**: 3ac4885
- **brier_score**: 0.0681
- **best_so_far**: 0.0665
- **improved**: False
- **gate**: ACCEPT
- **status**: discard
- **action**: REVERTED
- **current_head**: edc5a01

## Confidence Bands

  0.50-0.60: n=2, accuracy=100%
  0.60-0.70: n=3, accuracy=100%
  0.70-0.80: n=6, accuracy=100%

## Last 30 lines

```
  [backtest] skipped (LLM error): Will Russia and Ukraine sign a formal ceasefire ag
  [backtest] skipped (LLM error): Will Tesla deliver fewer than 400,000 vehicles in 

============================================================
POLYMARKET EVAL HARNESS SUMMARY
============================================================

[BACKTEST]  n=18
  Brier score : 0.0681
  ECE         : 0.1783
  Prompt hash : f3a00f38062c
  Confidence bands:
    0.50-0.60: n=2, accuracy=100%
    0.60-0.70: n=3, accuracy=100%
    0.70-0.80: n=6, accuracy=100%
    0.80+: n=7, accuracy=100%

  Mutation gate: [ACCEPT]

Traceback (most recent call last):
  File "C:\Users\spars\Desktop\polymarket-loop\eval\harness.py", line 469, in <module>
    main()
  File "C:\Users\spars\Desktop\polymarket-loop\eval\harness.py", line 465, in main
    print_summary(results)
  File "C:\Users\spars\Desktop\polymarket-loop\eval\harness.py", line 417, in print_summary
    print(f"    {gate['reason']}")
  File "C:\Users\spars\AppData\Roaming\uv\python\cpython-3.12.12-windows-x86_64-none\Lib\encodings\cp1252.py", line 19, in encode
    return codecs.charmap_encode(input,self.errors,encoding_table)[0]
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
UnicodeEncodeError: 'charmap' codec can't encode character '\u2192' in position 38: character maps to <undefined>
```
