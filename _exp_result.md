# Exp34 Result

- **commit**: 1718760
- **brier_score**: 0.0754
- **best_so_far**: 0.0468
- **improved**: False
- **gate**: REJECT
- **status**: discard
- **action**: REVERTED
- **current_head**: 25ebc7c

## Confidence Bands

  0.50-0.60: n=2, accuracy=50%
  0.60-0.70: n=2, accuracy=100%
  0.70-0.80: n=1, accuracy=0%

## Last 30 lines

```
Running backtest eval (calls LLM on 20 frozen historical markets)...

============================================================
POLYMARKET EVAL HARNESS SUMMARY
============================================================

[BACKTEST]  n=20
  Brier score : 0.0754
  ECE         : 0.162
  Prompt hash : c5f6909f880f
  Confidence bands:
    0.50-0.60: n=2, accuracy=50%
    0.60-0.70: n=2, accuracy=100%
    0.70-0.80: n=1, accuracy=0%
    0.80+: n=15, accuracy=100%

  Mutation gate: [REJECT]

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
