"use client";

import { useEffect, useState } from "react";
import { loadPreview } from "../../lib/supabase/preview";

export default function Compare() {
  const [result, setResult] = useState<unknown>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    loadPreview().then((data) => { if (active) setResult(data); }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "데이터를 불러오지 못했습니다.");
    });
    return () => { active = false; };
  }, []);
  return <main className="mx-auto max-w-4xl p-8">
    <h1 className="text-2xl font-semibold">후보지 비교</h1>
    {error ? <p role="alert" className="mt-6">{error}</p> : result === undefined ?
      <p role="status" className="mt-6">데이터를 불러오는 중입니다.</p> :
      <pre className="mt-6 overflow-auto rounded border border-slate-200 bg-white p-4 text-sm">{JSON.stringify(result, null, 2)}</pre>}
  </main>;
}
