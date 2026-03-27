# Experiment Result

- **brier_score**: None
- **gate**: Mutation gate: [REJECT]
- **exit_code**: 1

## Last 80 lines of output

```
Running backtest eval (calls LLM on 20 frozen historical markets)...

============================================================
POLYMARKET EVAL HARNESS SUMMARY
============================================================

[BACKTEST]  n=20
  Brier score : 0.074
  ECE         : 0.1765
  Prompt hash : 6357c3cdcbd1
  Confidence bands:
    0.50-0.60: n=4, accuracy=75%
    0.60-0.70: n=1, accuracy=100%
    0.70-0.80: n=4, accuracy=100%
    0.80+: n=11, accuracy=100%

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
