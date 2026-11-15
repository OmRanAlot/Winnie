"""Register the deployed Stable Spectrum webhook and save its secret locally, never to stdout."""
import argparse
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[3]


def register(url, *, env_file=None, session=None):
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname in (None,'localhost') or parsed.username or parsed.password:
        raise ValueError('Use the deployed public HTTPS webhook URL.')
    env_path=Path(env_file or ROOT/'backend/.env')
    config={**dotenv_values(ROOT/'.env'),**dotenv_values(ROOT/'messaging/.env'),**dotenv_values(env_path)}
    project=config.get('WINNIE_PHOTON_PROJECT_ID') or config.get('PROJECT_ID')
    secret=config.get('WINNIE_PHOTON_PROJECT_SECRET') or config.get('PROJECT_SECRET')
    if not project or not secret:
        raise ValueError('Configure Photon project credentials in messaging/.env or backend/.env.')
    client=session or httpx.Client(timeout=20,follow_redirects=False)
    try:
        response=client.get(url)
        if response.status_code!=200 or response.json().get('integration')!='winnie-photon-spectrum':
            raise ValueError('Deploy the updated backend first. The webhook route is not available.')
        endpoint=f'https://spectrum.photon.codes/projects/{project}/webhooks/'
        existing=client.get(endpoint,auth=(project,secret))
        existing.raise_for_status()
        matches=[r for r in existing.json()['data'] if r['webhookUrl']==url]
        if matches:
            if config.get('WINNIE_PHOTON_WEBHOOK_ID')==matches[0]['id'] and config.get('WINNIE_PHOTON_WEBHOOK_SECRET'):
                env_path.parent.mkdir(parents=True,exist_ok=True)
                for key,value in {'WINNIE_PHOTON_PROJECT_ID':project,'WINNIE_PHOTON_PROJECT_SECRET':secret,
                    'WINNIE_PHOTON_WEBHOOK_ID':matches[0]['id'],
                    'WINNIE_PHOTON_WEBHOOK_SECRET':config['WINNIE_PHOTON_WEBHOOK_SECRET']}.items():
                    set_key(env_path,key,value)
                return matches[0]['id'],env_path
            raise ValueError('URL already registered; its signing secret is not saved here. Preserve the existing registration and configure its secret manually.')
        env_path.parent.mkdir(parents=True,exist_ok=True)
        # Reserve a private, gitignored recovery file before requesting a one-time secret.
        descriptor,recovery_path=tempfile.mkstemp(prefix='.env.photon-recovery-',dir=env_path.parent)
        with os.fdopen(descriptor,'w',encoding='utf-8') as recovery:
            response=client.post(endpoint,auth=(project,secret),json={'webhookUrl':url})
            response.raise_for_status()
            data=response.json()['data']
            values={'WINNIE_PHOTON_WEBHOOK_SECRET':data['signingSecret'],
                'WINNIE_PHOTON_WEBHOOK_ID':data['id'],'WINNIE_PHOTON_PROJECT_ID':project,
                'WINNIE_PHOTON_PROJECT_SECRET':secret}
            json.dump(values,recovery)
            recovery.flush()
            os.fsync(recovery.fileno())
        for key,value in values.items():
            set_key(env_path,key,value)
        Path(recovery_path).unlink()
        return data['id'],env_path
    finally:
        if session is None:
            client.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='https://hack-princeton-514716.web.app/api/photon/webhook')
    args=parser.parse_args()
    try:
        identifier,path=register(args.url)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError):
        # Provider exception details can contain authorization headers or credentials.
        print('Registration not completed. Verify deployment, existing webhook settings and project credentials. No secret was printed.')
        return 1
    print(f'Webhook {identifier} registered. Secret saved in {path}; upload it with the Photon deployment script. Do not commit that file.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
