import urllib.request
import re
import sys

url = 'https://hh.ru/employer/600589'
req = urllib.request.Request(url, headers={'User-Agent': 'job-aggregator-diploma/1.0'})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read().decode('utf-8', errors='replace')
except Exception as e:
    print('FETCH-ERR', e)
    sys.exit(1)

print('LEN', len(html))
markers = ['aggregateRating', 'ratingValue', '"rating"', 'рейтинг', 'class="rating"', 'data-qa']
for m in markers:
    if m in html:
        print('HAS', m)

print('\n---SNIPPET START---\n')
print(html[:2000])
print('\n---SNIPPET END---\n')

m = re.search(r'(рейтинг|rating).{0,80}?([0-5][\\.,][0-9])', html, re.I | re.S)
if m:
    print('\nFOUND NEAR WORD:', m.group(0))
else:
    m2 = re.search(r'([0-5][\\.,][0-9])', html)
    if m2:
        print('\nFOUND NUMBER:', m2.group(1))
    else:
        print('\nNO VISIBLE RATING PATTERN FOUND')
