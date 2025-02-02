import os
from copy import deepcopy

from django.db.models import QuerySet

from accounts.const import AutomationTypes, Connectivity, SecretType
from common.utils import get_logger
from ..base.manager import AccountBasePlaybookManager

logger = get_logger(__name__)


class VerifyAccountManager(AccountBasePlaybookManager):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.host_account_mapper = {}

    def prepare_runtime_dir(self):
        path = super().prepare_runtime_dir()
        ansible_config_path = os.path.join(path, 'ansible.cfg')

        with open(ansible_config_path, 'w') as f:
            f.write('[ssh_connection]\n')
            f.write('ssh_args = -o ControlMaster=no -o ControlPersist=no\n')
        return path

    def host_callback(self, host, asset=None, account=None, automation=None, path_dir=None, **kwargs):
        host = super().host_callback(
            host, asset=asset, account=account,
            automation=automation, path_dir=path_dir, **kwargs
        )
        if host.get('error'):
            return host

        # host['ssh_args'] = '-o ControlMaster=no -o ControlPersist=no'
        accounts = asset.accounts.all()
        accounts = self.get_accounts(account, accounts)
        inventory_hosts = []

        for account in accounts:
            h = deepcopy(host)
            h['name'] += '(' + account.username + ')'
            self.host_account_mapper[h['name']] = account
            secret = account.secret

            private_key_path = None
            if account.secret_type == SecretType.SSH_KEY:
                private_key_path = self.generate_private_key_path(secret, path_dir)
                secret = self.generate_public_key(secret)

            h['secret_type'] = account.secret_type
            h['account'] = {
                'name': account.name,
                'username': account.username,
                'secret_type': account.secret_type,
                'secret': secret,
                'private_key_path': private_key_path
            }
            if account.platform.type == 'oracle':
                h['account']['mode'] = 'sysdba' if account.privileged else None
            inventory_hosts.append(h)
        return inventory_hosts

    @classmethod
    def method_type(cls):
        return AutomationTypes.verify_account

    def get_accounts(self, privilege_account, accounts: QuerySet):
        snapshot_account_usernames = self.execution.snapshot['accounts']
        if '*' not in snapshot_account_usernames:
            accounts = accounts.filter(username__in=snapshot_account_usernames)
        return accounts

    def on_host_success(self, host, result):
        account = self.host_account_mapper.get(host)
        account.set_connectivity(Connectivity.OK)

    def on_host_error(self, host, error, result):
        account = self.host_account_mapper.get(host)
        account.set_connectivity(Connectivity.ERR)
