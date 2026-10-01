import Link from 'next/link';
import { CandidateForm } from '../../components/candidate/CandidateForm';
export default function NewCandidatePage() {
  return <main className="page"><Link href="/compare">← 후보 비교</Link><h1>후보 등록</h1>
    <p>서울 · 학원업 · 반경 800m</p><CandidateForm /></main>;
}
