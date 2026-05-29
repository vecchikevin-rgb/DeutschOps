import sys
from anki_feeder import feed

date = sys.argv[1]
feed(f"data/lezione_{date}.json", lesson_date=date)