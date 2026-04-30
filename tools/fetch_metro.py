"""
Fetch metro station data from HH.ru API and save as tools/metro_hh.json.

Output structure:
[
  {
    "city_id": "1",
    "city_name": "Москва",
    "lines": [
      {
        "id": 1,
        "name": "Сокольническая",
        "hex_color": "E42313",
        "stations": [
          {"id": "s1", "name": "Бульвар Рокоссовского", "lat": ..., "lng": ...},
          ...
        ]
      },
      ...
    ]
  },
  ...
]
"""

import json
import time
from urllib.request import Request, urlopen

HEADERS = {
    'User-Agent': 'job-aggregator-diploma/1.0 (+http://localhost:8000)',
    'Accept': 'application/json',
    'Accept-Language': 'ru-RU,ru;q=0.9',
}
BASE    = 'https://api.hh.ru'


def fetch(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    print('Fetching city list from /metro …')
    cities = fetch(f'{BASE}/metro')

    result = []
    for city in cities:
        city_id   = city['id']
        city_name = city['name']
        print(f'  Fetching {city_name} (id={city_id}) …')
        try:
            detail = fetch(f'{BASE}/metro/{city_id}')
            lines = []
            for line in detail.get('lines', []):
                stations = []
                for s in line.get('stations', []):
                    stations.append({
                        'id':   s['id'],
                        'name': s['name'],
                        'lat':  s.get('lat'),
                        'lng':  s.get('lng'),
                    })
                lines.append({
                    'id':        line['id'],
                    'name':      line['name'],
                    'hex_color': line.get('hex_color', 'aaaaaa'),
                    'stations':  stations,
                })
            result.append({
                'city_id':   city_id,
                'city_name': city_name,
                'lines':     lines,
            })
            time.sleep(0.3)   # be polite
        except Exception as e:
            print(f'    ERROR: {e}')

    out_path = __file__.replace('fetch_metro.py', 'metro_hh.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'Saved {len(result)} cities → {out_path}')


if __name__ == '__main__':
    main()
