import Image from "next/image";

import { FaqList } from "./faq-list";

export function FaqSection() {
  return (
    <>
      <section id="faq" className="bg-[#fdfaf1] absolute left-[39px] top-[9288px] w-[1362px] h-[1013px] overflow-clip">
        <div className="absolute h-[1013px] left-0 top-0 w-[1362px]">
          <div className="absolute inset-0 opacity-50 overflow-hidden pointer-events-none">
            <Image alt="" className="absolute h-[100.02%] left-[-2.28%] max-w-none top-[-0.01%] w-[104.55%]" src="/assets/landing-v2/image-2661-0b8f242f3b.png" width={1424} height={1013} />
          </div>
        </div>
        <h2 className="-translate-x-1/2 [word-break:break-word] absolute font-medium leading-[1.028] left-[680.5px] not-italic text-[#262627] text-[63px] text-center top-[79px] tracking-[-3.15px] whitespace-nowrap">
          Got questions?
          <br aria-hidden />
          We’ve got answers
        </h2>
        <FaqList />
      </section>
    </>
  );
}
