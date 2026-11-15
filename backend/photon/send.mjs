// Request-scoped outbound calls only. Never subscribe to the incoming stream.
import { createGrpcClient } from '@photon-ai/advanced-imessage/grpc';
export async function deliver(input, env = process.env, fetcher = fetch, factory = createGrpcClient) {
  const project = env.WINNIE_PHOTON_PROJECT_ID;
  const secret = env.WINNIE_PHOTON_PROJECT_SECRET;
  if (!project || !secret) throw new Error('Photon credentials missing');
  const response = await fetcher(`https://spectrum.photon.codes/projects/${encodeURIComponent(project)}/imessage/tokens`, {
    method:'POST',headers:{Authorization:`Basic ${Buffer.from(`${project}:${secret}`).toString('base64')}`},
    signal:AbortSignal.timeout(15000),redirect:'error',
  });
  if (!response.ok) throw new Error('Photon authorization failed');
  const {data} = await response.json();
  let token, address;
  if (data.type === 'shared') { token=data.token; address='imessage.spectrum.photon.codes:443'; }
  else if (data.type === 'dedicated') {
    const candidates=Object.keys(data.auth || {}).filter(id => !input.phone || data.numbers[id]===input.phone);
    if(candidates.length!==1 || !/^[a-zA-Z0-9-]+$/.test(candidates[0])) throw new Error('Ambiguous Photon line');
    token=data.auth[candidates[0]]; address=`${candidates[0]}.imsg.photon.codes:443`;
  } else throw new Error('Unknown Photon line type');
  const client=factory({address,token,tls:true,retry:false,timeout:15000});
  try {
    const chat=input.space_id || (await client.chats.create([input.recipient])).chat.guid;
    const sent=await client.messages.sendText(chat,input.text,{clientMessageId:input.dedupe_key});
    if(!sent?.guid || sent.isSent!==true || sent.sendErrorCode) throw new Error('Photon send not confirmed');
    return {provider_id:sent.guid};
  } finally {await client.close();}
}
if (process.argv[1] && import.meta.url === (await import('node:url')).pathToFileURL(process.argv[1]).href) {
  try {
    let input=''; for await (const chunk of process.stdin) {input+=chunk; if(input.length>50000) throw new Error('Too large');}
    const result=await deliver(JSON.parse(input)); process.stdout.write(JSON.stringify(result));
  } catch {process.stderr.write('Photon outbound send was not confirmed.\n'); process.exitCode=1;}
}
