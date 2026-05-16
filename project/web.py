from flask import Flask, render_template, url_for
from jinja2 import Environment, FileSystemLoader
from config import *

app = Flask(__name__)

# Create a custom Jinja2 environment
template_loader = FileSystemLoader(searchpath="templates")
env = Environment(loader=template_loader)

env.globals['url_for'] = url_for

# Use the custom environment in your Flask application
app.jinja_env = env

@app.route('/')
@app.route('/<string>/')
def subscription(string=None):
    # Create a new session
    session = Session()
    if not string:
        return '404'
    
    # Query the Subscription table and filter by the link
    subscription = session.query(Subscription).filter_by(link=string).first()

    if not subscription:
        return '404'
    
    # Get the client traffics using the email from the subscription
    _ , traffics = calculate_traffic_up_and_down(subscription.id)
    if traffics:
        remain = "{:.1f}".format(max(subscription.gigabytes - (traffics[1] + traffics[0]), 0))
        traffics = tuple("{:.1f}".format(num) for num in traffics)
        remain_link = f'\nvless://1@1.1.1.1:80?type=tcp#{"فعال" if subscription.is_active else "غیرفعال"}|باقیمانده:{remain}گیگابایت\n'
    else:
        return 'error'
    session.close()
    
    # Render the template with the subscription details and traffics
    return render_template('webpage.html',
                            subscription=subscription,
                            traffics=traffics,
                            max=max,
                            bot_domain=bot_domain,
                            links= '\n' + '\n'.join(subscription.links.split(', ')),
                            remain=remain,
                            remain_link=remain_link)


if __name__ == '__main__':
    app.run(host='127.0.0.1')
