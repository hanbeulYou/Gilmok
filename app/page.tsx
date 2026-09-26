import Link from "next/link";

export default function Home() {
  return <main className="mx-auto max-w-4xl p-8"><h1 className="text-2xl font-semibold">길목</h1><Link className="mt-6 inline-block underline" href="/compare">후보지 비교</Link></main>;
}
