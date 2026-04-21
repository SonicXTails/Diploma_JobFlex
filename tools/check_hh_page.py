import urllib.request

url = 'https://hh.ru/employer/5490091'
req = urllib.request.Request(url, headers={'User-Agent': 'job-aggregator-diploma/1.0'})
with urllib.request.urlopen(req, timeout=15) as r:
    html = r.read().decode('utf-8')

print('Length:', len(html))
for token in ['Рейтинг', 'рейтинг', 'rating', 'ratingValue', 'data-rating', 'rating-average', 'employer-rating']:
    idx = html.find(token)
    print(token, '->', idx)
    if idx != -1:
        print('--- snippet ---')
        print(html[max(0, idx-120):idx+120])
        print('--- end ---\n')
