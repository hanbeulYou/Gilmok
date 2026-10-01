import { ensureSession } from '../supabase/session';

const messages: Record<string, string> = {
  authentication_required: '인증이 만료됐습니다. 인증을 다시 시도해 주세요.',
  daily_limit_reached: '오늘 주소 조회 한도(100회)를 사용했습니다. 자정 이후 다시 시도해 주세요.',
  outside_seoul: '현재는 서울 안의 주소만 등록할 수 있습니다.',
  location_needs_review: '주소와 건물 도형이 일치하지 않거나 겹칩니다. 주소를 다시 확인해 주세요.',
  location_not_verified: '정확한 건물 위치를 확인하지 못했습니다. 주소를 다시 선택해 주세요.',
  address_selection_changed: '주소 결과가 변경됐습니다. 다시 검색해 주세요.',
  address_provider_not_configured: '주소 검색 연결을 준비 중입니다. 잠시 후 다시 시도해 주세요.',
};
export async function addressRequest<T>(body: unknown, signal?: AbortSignal): Promise<T> {
  const session = await ensureSession();
  const response = await fetch('/api/address-search', { method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session.access_token}` },
    body: JSON.stringify(body), cache: 'no-store', signal: signal ?? AbortSignal.timeout(55000),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(messages[data.error] ?? '주소 조회에 실패했습니다. 다시 시도해 주세요.');
  return data as T;
}
