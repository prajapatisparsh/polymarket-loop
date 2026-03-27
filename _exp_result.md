# Exp28 Result

- **commit**: 3118dc4
- **brier_score**: 0.0509
- **best_so_far**: 0.0504
- **improved**: False
- **gate**: ACCEPT
- **status**: discard
- **action**: REVERTED
- **current_head**: bf30c83

## Confidence Bands

  0.50-0.60: n=2, accuracy=100%
  0.60-0.70: n=1, accuracy=100%
  0.70-0.80: n=4, accuracy=100%

## Last 30 lines

```
Running backtest eval (calls LLM on 20 frozen historical markets)...

============================================================
POLYMARKET EVAL HARNESS SUMMARY
============================================================

[BACKTEST]  n=20
  Brier score : 0.0509
  ECE         : 0.1885
  Prompt hash : 2fc29eede4ca
  Confidence bands:
    0.50-0.60: n=2, accuracy=100%
    0.60-0.70: n=1, accuracy=100%
    0.70-0.80: n=4, accuracy=100%
    0.80+: n=13, accuracy=100%

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
