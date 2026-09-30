import { createClient } from '@supabase/supabase-js';
import { AddressError, createAddressProvider, parseSelection } from '../../../lib/geo/address-server';

export const runtime = 'nodejs';
export const preferredRegion = 'icn1';
export const dynamic = 'force-dynamic';
export const maxDuration = 60;

export async function POST(request: Request): Promise<Response> {
  const reply = (body: unknown, status = 200) => Response.json(body, {
    status, headers: { 'Cache-Control': 'private, no-store' },
  });
  try {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL, key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
    if (!url || !key) throw new AddressError('address_provider_not_configured', 503);
    const authorization = request.headers.get('authorization') ?? '';
    if (!/^Bearer \S+$/.test(authorization)) throw new AddressError('authentication_required', 401);
    const client = createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false },
      global: { headers: { Authorization: authorization } } });
    const { data: auth, error: authError } = await client.auth.getUser(authorization.slice(7));
    if (authError || !auth.user) throw new AddressError('authentication_required', 401);
    if (Number(request.headers.get('content-length')) > 8192) throw new AddressError('invalid_request', 400);
    const text = await request.text();
    if (text.length > 8192) throw new AddressError('invalid_request', 400);
    let body;
    try { body = JSON.parse(text); } catch { throw new AddressError('invalid_request', 400); }
    if (!body || typeof body !== 'object') throw new AddressError('invalid_request', 400);
    const provider = createAddressProvider({ juso: process.env.JUSO_API_KEY, vworld: process.env.VWORLD_API_KEY }, async source => {
      const { data, error } = await client.rpc('claim_address_call', { provider: source });
      if (error) throw new AddressError('address_limit_unavailable', 503);
      if (data !== true) throw new AddressError('daily_limit_reached', 429);
    });
    if (body.action === 'search') {
      if (typeof body.query !== 'string' || body.query.trim().length < 2 || body.query.length > 100)
        throw new AddressError('invalid_query', 400);
      return reply(await provider.search(body.query.trim()));
    }
    if (body.action !== 'locate') throw new AddressError('invalid_request', 400);
    let selection;
    try { selection = parseSelection(body.selection); } catch { throw new AddressError('invalid_selection', 400); }
    const location = await provider.locate(selection);
    if (location.status !== 'ready') throw new AddressError('location_not_verified', 422);
    const { data: resolved, error } = await client.rpc('resolve_candidate_location', {
      lat: location.lat, lng: location.lng, pnu: selection.pnu,
    });
    if (error || !resolved) throw new AddressError('location_check_unavailable', 503);
    if (!['matched', 'footprint_missing'].includes(resolved.status))
      throw new AddressError(resolved.status === 'outside_seoul' ? 'outside_seoul' : 'location_needs_review', 422);
    return reply({ selection, location, resolved });
  } catch (error) {
    // Errors never echo provider URLs, credentials, addresses or raw responses.
    return reply({ error: error instanceof AddressError ? error.code : 'address_request_failed' },
      error instanceof AddressError ? error.status : 502);
  }
}
