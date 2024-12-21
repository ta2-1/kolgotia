import qrcode
import qrcode.image.svg
from transliterate import translit
import json
from jinja2 import Environment, FileSystemLoader

from tickets import tickets
import re
'''
if method == 'basic':
    # Simple factory, just a set of rects.
    factory = qrcode.image.svg.SvgImage
elif method == 'fragment':
    # Fragment factory (also just a set of rects)
    factory = qrcode.image.svg.SvgFragmentImage
else:
    # Combined path factory, fixes white space that may occur when zooming
'''
factory = qrcode.image.svg.SvgPathImage

for ticket in tickets:
    id = translit(ticket['description'], 'ru', reversed=True)
    ticket['_id'] = re.sub(r'[\W_]+', '', id).lower()
    ticket['qr'] = qrcode.make('https://t.me/kolgotia_lottery_bot?start=register_' + ticket['_id'], image_factory=factory, box_size=6).to_string().decode("utf-8")
    
#print(tickets)
json.dump([{'_id': t['_id'], 'description': t['description']} for t in tickets], open('tickets.json', 'w'), indent=4, ensure_ascii=False)

environment = Environment(loader=FileSystemLoader("templates/"))
template = environment.get_template("results.html")
content = template.render(dict(tickets=tickets))
with open("tickets.html", "w") as file:
    file.write(content)

print(f"Tickets { len(tickets) } are generated")
