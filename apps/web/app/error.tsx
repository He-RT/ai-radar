"use client";
import { useEffect } from "react";
import { EmptyState } from "../components/atlas";
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) { useEffect(() => { console.error(error); }, [error]); return <div className="contentPage"><EmptyState title="公共数据暂时不可用" body="API 没有返回可验证读数，或返回内容未通过契约校验。系统不会用演示数据替代生产事实；请稍后重试。" /><button className="button" type="button" onClick={reset}>重新读取 <span>↻</span></button></div>; }
