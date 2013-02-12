import os

from fabric.api import task, run, env, cd, settings, puts
from fabtools.vagrant import ssh_config, _settings_dict
import fabtools  # NOQA
from fabtools import require

import mechanize


@task
def vagrant(name=''):
    config = ssh_config(name)
    extra_args = _settings_dict(config)
    env.update(extra_args)
    env['user'] = 'root'

    env['mysql_user'] = 'root'
    env['mysql_password'] = os.environ.get('MYSQL_PASSWORD', 'password')


@task
def piwik_config():
    env['piwik'] = {
        'unix_user': 'piwik',
        'url': 'piwik.stephane-klein.info',

        'database_name': 'piwik',
        'database_user': 'piwik',
        'database_password': os.environ.get('PIWIK_MYSQL_PASSWORD', 'password'),

        'piwik_admin_user': 'admin',
        'piwik_admin_password': os.environ.get('PIWIK_ADMIN_PASSWORD', 'password'),
        'piwik_admin_mail': 'contact@stephane-klein.info',

        'first_site_name': 'stephane-klein.info',
        'first_site_url': 'http://stephane-klein.info',
        'first_site_timezone': 'Europe/Paris',
        'first_site_ecommerce': False
    }

VIRTUALHOST_TPL = """
{{default aliases=[] }}
{{default allow_override=None }}
<VirtualHost *:80>
    ServerName {{hostname}}
    {{for a in aliases}}
    ServerAlias {{a}}
    {{endfor}}

    DocumentRoot {{document_root}}

    <Directory {{document_root}}>
        Options Indexes FollowSymLinks MultiViews

        {{if allow_override}}
        AllowOverride {{allow_override}}
        {{else}}
        AllowOverride All
        {{endif}}

        Order allow,deny
        allow from all
    </Directory>
</VirtualHost>
"""


def _add_user(*args, **kwargs):
    require.user(*args, **kwargs)
    if 'name' not in kwargs:
        user = args[0]
    else:
        user = kwargs['name']

    if not fabtools.files.is_file('/home/%s/.ssh/authorized_keys' % user):
        run('mkdir -p /home/%s/.ssh/' % user)
        run('cp /root/.ssh/authorized_keys /home/%s/.ssh/' % user)
        run('chown %(user)s:%(user)s /home/%(user)s/.ssh/ -R' % {'user': user})


@task
def install_piwik():
    if 'piwik' not in env:
        puts('"piwik" configuration missing in env variable, append "piwik_config" task')
        return

    fabtools.require.system.locale('fr_FR.UTF-8')

    fabtools.deb.update_index()
    fabtools.deb.preseed_package('mysql-server', {
        'mysql-server/root_password': ('password', env['mysql_password']),
        'mysql-server/root_password_again': ('password', env['mysql_password']),
    })
    require.deb.packages([
        'build-essential',
        'devscripts',
        'locales',
        'apache2',
        'mysql-server',
        'mysql-client',
        'php5',
        'php5-mysql',
        'php5-gd',
        'libapache2-mod-php5',
        'vim',
        'mc',
        'curl',
    ])

    _add_user(
        name='piwik',
        password=None,
        shell='/bin/bash'
    )
    require.mysql.user(
        env['piwik']['database_user'],
        env['piwik']['database_password']
    )
    require.mysql.database(
        env['piwik']['database_name'],
        owner=env['piwik']['database_user']
    )

    with settings(user=env['piwik']['unix_user']):
        with cd('/home/%s/' % env['piwik']['unix_user']):
            require.file(url='http://builds.piwik.org/latest.zip')
            run('unzip latest.zip')
            run('mv piwik www')

    run('rm /etc/apache2/sites-enabled/000-default -rf')
    require.apache.site(
        env['piwik']['url'],
        template_contents=VIRTUALHOST_TPL,
        hostname=env['piwik']['url'],
        document_root='/home/%s/www/' % env['piwik']['unix_user'],
        enable=True
    )
    fabtools.apache.restart()
    run('chown -R www-data:www-data /home/%s/www' % env['piwik']['unix_user'])

    br = mechanize.Browser()
    br.open("http://%s/index.php" % env['piwik']['url'])
    with cd('/home/%s/' % env['piwik']['unix_user']):
        run('chmod -R 0755 www/tmp')
        run('chmod -R 0755 www/tmp/templates_c/')
        run('chmod -R 0755 www/tmp/cache/')
        run('chmod -R 0755 www/tmp/assets/')
        run('chmod -R 0755 www/tmp/tcpdf/')

    br.open('http://%s/index.php?action=systemCheck' % env['piwik']['url'])
    br.open('http://%s/index.php?action=databaseSetup' % env['piwik']['url'])
    br.select_form(name="databasesetupform")
    br['host'] = '127.0.0.1'
    br['username'] = env['piwik']['database_user']
    br['password'] = env['piwik']['database_password']
    br['dbname'] = env['piwik']['database_name']
    br['tables_prefix'] = 'piwik_'
    br['adapter'] = ['PDO_MYSQL']

    br.submit()
    br.open('http://%s/index.php?action=generalSetup&module=Installation' % env['piwik']['url'])
    br.select_form(name="generalsetupform")
    br['login'] = env['piwik']['piwik_admin_user']
    br['password'] = env['piwik']['piwik_admin_password']
    br['password_bis'] = env['piwik']['piwik_admin_password']
    br['email'] = env['piwik']['piwik_admin_mail']
    br['subscribe_newsletter_security'] = False
    br['subscribe_newsletter_community'] = False
    br.submit()

    br.open('http://%s/index.php?action=firstWebsiteSetup&module=Installation' % env['piwik']['url'])
    br.select_form(name="websitesetupform")
    br['siteName'] = env['piwik']['first_site_name']
    br['url'] = env['piwik']['first_site_url']
    br['timezone'] = [env['piwik']['first_site_timezone']]
    br['ecommerce'] = ['1' if env['piwik']['first_site_name'] else '0']
    br.submit()

    br.open('http://%s/index.php?action=finished&module=Installation' % env['piwik']['url'])


@task
def uninstall_piwik():
    if 'piwik' not in env:
        puts('"piwik" configuration missing in env variable, append "piwik_config" task')
        return

    fabtools.mysql.drop_database(env['piwik']['database_name'])
    with cd('/home/%s/' % env['piwik']['unix_user']):
        run('rm -f latest.zip')
        run('rm -rf piwik')
        run('rm -rf *.html')
        run('rm -rf www')

    fabtools.apache.disable_site(env['piwik']['url'])
    fabtools.apache.restart()
