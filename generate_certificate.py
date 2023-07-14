#!/usr/bin/env python

from ansible.module_utils.basic import AnsibleModule
import os
import subprocess

def run_module():
    module = AnsibleModule(
        argument_spec=dict(
            cert_file=dict(type='str', required=True),
            key_file=dict(type='str', required=True),
            pub_key_file=dict(type='str', required=True),
            common_name=dict(type='str', required=True),
        ),
        supports_check_mode=True
    )

    cert_file = module.params['cert_file']
    key_file = module.params['key_file']
    pub_key_file = module.params['pub_key_file']
    common_name = module.params['common_name']

    if module.check_mode:
        return module.exit_json(changed=False)

    try:
        openssl_config = """
        distinguished_name = req_distinguished_name
        [req_distinguished_name]
        [v3_req_client]
        extendedKeyUsage = clientAuth
        subjectAltName = otherName:1.3.6.1.4.1.311.20.2.3;UTF8:{0}@localhost
        """.format(common_name)
        
        with open('openssl.conf', 'w') as f:
            f.write(openssl_config)
        
        os.environ['OPENSSL_CONF'] = 'openssl.conf'
        
        subprocess.check_call(['openssl', 'req', '-x509', '-nodes', '-days', '3650', '-newkey', 'rsa:2048', '-out', 
                               cert_file, '-outform', 'PEM', '-keyout', key_file, '-subj', 
                               '/CN={}'.format(common_name), '-extensions', 'v3_req_client'])
        subprocess.check_call(['ssh-keygen', '-f', key_file, '-y'], stdout=open(pub_key_file, 'w'))

    except subprocess.CalledProcessError as e:
        module.fail_json(msg='Failed to create certificates: {}'.format(str(e)), changed=False)

    finally:
        os.remove('openssl.conf')
    
    module.exit_json(changed=True)

def main():
    run_module()

if __name__ == '__main__':
    main()
