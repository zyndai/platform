import Image from "next/image";
import Link from "next/link";

export function CtaBannerSection() {
  return (
    <>
      <div className="absolute left-[37px] top-[4281px] w-[1362px] h-[474px] overflow-clip">
        <Image alt="" className="absolute inset-0 max-w-none object-cover pointer-events-none size-full" src="/assets/landing-v2/frame-2147261358-df69ab0a91.png" width={1362} height={474} />
        <h2 className="[word-break:break-word] absolute font-medium leading-[1.028] left-[345px] not-italic text-[#262627] text-[63px] top-[172px] tracking-[-3.15px] whitespace-nowrap">
          Your next connection
          <br aria-hidden />
          could be just a link away.
        </h2>
        <Link href="/create" className="absolute content-stretch drop-shadow-[0px_4px_4px_rgba(0,0,0,0.38)] flex h-[63px] items-center justify-center left-[1051px] p-[10px] rounded-[35px] top-[349px] w-[269px]">
          <span aria-hidden className="absolute bg-[#262627] inset-0 pointer-events-none rounded-[35px]" />
          <span className="[word-break:break-word] font-semibold leading-[normal] not-italic relative shrink-0 text-[17px] text-center text-white tracking-[-0.68px] whitespace-nowrap">
            Create your Profile
          </span>
          <span className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_12px_0px_rgba(255,255,255,0.25)]" />
        </Link>
      </div>
    </>
  );
}
