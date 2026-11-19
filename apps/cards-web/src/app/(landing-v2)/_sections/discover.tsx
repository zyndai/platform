/* eslint-disable @next/next/no-img-element -- static SVG icons from the design; next/image adds nothing for vectors */
import Image from "next/image";
import Link from "next/link";

export function DiscoverSection() {
  return (
    <>
      <section id="discover" className="absolute bg-[#fdfaf1] h-[1559px] left-[39px] overflow-clip top-[4807px] w-[1362px]">
        <h2 className="[word-break:break-word] absolute font-medium leading-[1.028] left-[44px] not-italic text-[#262627] text-[63px] top-[84px] tracking-[-3.15px] whitespace-nowrap">
          Meet the right people.
          <br aria-hidden />
          Not just followers.
        </h2>
        <div className="absolute h-[441px] left-[681px] top-[-22px] w-[628px]">
          <Image alt="" className="absolute inset-0 max-w-none object-cover pointer-events-none size-full" src="/assets/landing-v2/image-2656-8e521353f9.png" width={628} height={441} />
        </div>
        <div className="absolute h-[539px] left-[32px] top-[879px] w-[768px]">
          <Image alt="" className="absolute inset-0 max-w-none object-cover opacity-35 pointer-events-none size-full" src="/assets/landing-v2/image-2656-8e521353f9.png" width={768} height={539} />
        </div>
        <div className="absolute h-[274px] left-[919px] top-[1111px] w-[390px]">
          <Image alt="" className="absolute inset-0 max-w-none object-cover opacity-35 pointer-events-none size-full" src="/assets/landing-v2/image-2656-8e521353f9.png" width={390} height={274} />
        </div>
        <div className="absolute h-[322px] left-[461px] top-[596px] w-[458px]">
          <Image alt="" className="absolute inset-0 max-w-none object-cover opacity-20 pointer-events-none size-full" src="/assets/landing-v2/image-2656-8e521353f9.png" width={458} height={322} />
        </div>
        <p className="[word-break:break-word] absolute font-light leading-[normal] left-[52px] not-italic text-[21px] text-black top-[230px] w-[519px]">
          Discover collaborators, creators and fellow builders who share your interests, skills and goals — and actually want to work (or build) together.
        </p>
        <Link href="/network" className="absolute content-stretch drop-shadow-[0px_4px_4px_rgba(0,0,0,0.38)] flex h-[63px] items-center justify-center left-[566px] p-[10px] rounded-[35px] top-[1434px] w-[269px]">
          <span aria-hidden className="absolute bg-[#262627] inset-0 pointer-events-none rounded-[35px]" />
          <span className="[word-break:break-word] font-semibold leading-[normal] not-italic relative shrink-0 text-[17px] text-center text-white tracking-[-0.68px] whitespace-nowrap">
            Explore Networking
          </span>
          <span className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_12px_0px_rgba(255,255,255,0.25)]" />
        </Link>
        <div className="absolute h-[219px] left-[550px] top-[720px] w-[308px]">
          <Image alt="" className="absolute inset-0 max-w-none object-cover pointer-events-none size-full" src="/assets/landing-v2/image-2659-7b88293419.png" width={308} height={219} />
        </div>
        <div className="absolute bg-white border-8 border-solid border-white left-[211px] overflow-clip rounded-[120px] shadow-[0px_4px_4px_0px_rgba(0,0,0,0.25)] size-[202px] top-[720px]">
          <div className="absolute flex h-[300px] items-center justify-center left-[-7px] top-[-29px] w-[200.097px]">
            <div className="-scale-y-100 flex-none rotate-180">
              <div className="h-[300px] relative w-[200.097px]">
                <Image alt="" className="absolute inset-0 max-w-none object-cover pointer-events-none size-full" src="/assets/landing-v2/image-2666-0fe80f6168.png" width={200} height={300} />
              </div>
            </div>
          </div>
        </div>
        <div className="absolute content-stretch drop-shadow-[0px_4px_5.5px_rgba(0,0,0,0.18)] flex h-[39px] items-center justify-center left-[248px] p-[10px] rounded-[43px] top-[890px] w-[131px]">
          <div aria-hidden className="absolute bg-[#4e4e5a] inset-0 pointer-events-none rounded-[43px]" />
          <p className="[word-break:break-word] font-medium leading-[normal] not-italic relative shrink-0 text-[13px] text-center text-white tracking-[-0.52px] whitespace-nowrap">
            Content Creator
          </p>
          <div className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_14px_0px_rgba(255,255,255,0.18)]" />
        </div>
        <div className="absolute bg-white border-8 border-solid border-white left-[412px] overflow-clip rounded-[120px] shadow-[0px_4px_4px_0px_rgba(0,0,0,0.25)] size-[202px] top-[421px]">
          <div className="absolute flex h-[300px] items-center justify-center left-[-7px] top-[-29px] w-[200.097px]">
            <div className="-scale-y-100 flex-none rotate-180">
              <div className="h-[300px] relative w-[200.097px]">
                <Image alt="" className="absolute inset-0 max-w-none object-cover pointer-events-none size-full" src="/assets/landing-v2/image-2667-1c44d0d4ad.png" width={200} height={300} />
              </div>
            </div>
          </div>
        </div>
        <div className="absolute bg-white border-8 border-solid border-white left-[814px] overflow-clip rounded-[120px] shadow-[0px_4px_4px_0px_rgba(0,0,0,0.25)] size-[202px] top-[441px]">
          <div className="absolute flex h-[300px] items-center justify-center left-[-7px] top-[-29px] w-[200.097px]">
            <div className="-scale-y-100 flex-none rotate-180">
              <div className="h-[300px] relative w-[200.097px]">
                <Image alt="" className="absolute inset-0 max-w-none object-cover pointer-events-none size-full" src="/assets/landing-v2/rectangle-1430106958-e209af98cd.png" width={200} height={300} />
              </div>
            </div>
          </div>
        </div>
        <div className="absolute bg-white border-8 border-solid border-white left-[967px] overflow-clip rounded-[120px] shadow-[0px_4px_4px_0px_rgba(0,0,0,0.25)] size-[202px] top-[797px]">
          <div className="absolute flex h-[300px] items-center justify-center left-[-7px] top-[-8px] w-[200.097px]">
            <div className="-scale-y-100 flex-none rotate-180">
              <div className="h-[300px] relative w-[200.097px]">
                <div aria-hidden className="absolute inset-0 pointer-events-none">
                  <Image alt="" className="absolute max-w-none object-cover size-full" src="/assets/landing-v2/image-2666-0fe80f6168.png" width={200} height={300} />
                  <Image alt="" className="absolute max-w-none object-cover size-full" src="/assets/landing-v2/image-2668-09082652b2.png" width={200} height={300} />
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="absolute bg-white border-8 border-solid border-white left-[589px] overflow-clip rounded-[120px] shadow-[0px_4px_4px_0px_rgba(0,0,0,0.25)] size-[202px] top-[1038px]">
          <div className="absolute flex h-[300px] items-center justify-center left-[-7px] top-[-29px] w-[200.097px]">
            <div className="-scale-y-100 flex-none rotate-180">
              <div className="h-[300px] relative w-[200.097px]">
                <div className="absolute inset-0 overflow-hidden pointer-events-none">
                  <Image alt="" className="absolute h-[100.55%] left-[-2.87%] max-w-none top-[8.05%] w-full" src="/assets/landing-v2/image-2669-ec4e37a04f.png" width={200} height={302} />
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="absolute content-stretch drop-shadow-[0px_4px_5.5px_rgba(0,0,0,0.18)] flex h-[39px] items-center justify-center left-[619px] p-[10px] rounded-[43px] top-[1220px] w-[149px]">
          <div aria-hidden className="absolute bg-[#4e4e5a] inset-0 pointer-events-none rounded-[43px]" />
          <p className="[word-break:break-word] font-medium leading-[normal] not-italic relative shrink-0 text-[13px] text-center text-white tracking-[-0.52px] whitespace-nowrap">
            Product Designer
          </p>
          <div className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_14px_0px_rgba(255,255,255,0.18)]" />
        </div>
        <div className="absolute content-stretch drop-shadow-[0px_4px_5.5px_rgba(0,0,0,0.18)] flex h-[39px] items-center justify-center left-[1002px] p-[10px] rounded-[43px] top-[981px] w-[133px]">
          <div aria-hidden className="absolute bg-[#4e4e5a] inset-0 pointer-events-none rounded-[43px]" />
          <p className="[word-break:break-word] font-medium leading-[normal] not-italic relative shrink-0 text-[13px] text-center text-white tracking-[-0.52px] whitespace-nowrap">
            Illustrator
          </p>
          <div className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_14px_0px_rgba(255,255,255,0.18)]" />
        </div>
        <div className="absolute content-stretch drop-shadow-[0px_4px_5.5px_rgba(0,0,0,0.18)] flex h-[39px] items-center justify-center left-[840px] p-[10px] rounded-[43px] top-[623px] w-[150px]">
          <div aria-hidden className="absolute bg-[#4e4e5a] inset-0 pointer-events-none rounded-[43px]" />
          <p className="[word-break:break-word] font-medium leading-[normal] not-italic relative shrink-0 text-[13px] text-center text-white tracking-[-0.52px] whitespace-nowrap">
            Frontend Developer
          </p>
          <div className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_14px_0px_rgba(255,255,255,0.18)]" />
        </div>
        <div className="absolute flex inset-[33.82%_69.85%_56.54%_19.11%] items-center justify-center" style={{ containerType: "size" }}>
          <div className="flex-none h-[hypot(30.8186cqw,69.0996cqh)] rotate-[-24.05deg] w-[hypot(69.1814cqw,-30.9004cqh)]">
            <div className="relative size-full">
              <div className="absolute inset-[-3.52%_-7.02%_-10.56%_-7.02%]">
                <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/vector-2-e665717ec1.svg" />
              </div>
            </div>
          </div>
        </div>
        <div className="absolute flex inset-[25.66%_42.35%_64.72%_46.62%] items-center justify-center" style={{ containerType: "size" }}>
          <div className="flex-none h-[hypot(-30.6875cqw,69.2308cqh)] rotate-[23.92deg] w-[hypot(69.3125cqw,30.7692cqh)]">
            <div className="relative size-full">
              <div className="absolute inset-[-3.52%_-7.02%_-10.56%_-7.02%]">
                <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/vector-3-d274c97537.svg" />
              </div>
            </div>
          </div>
        </div>
        <div className="absolute flex inset-[42.33%_17.28%_50.24%_74.23%] items-center justify-center" style={{ containerType: "size" }}>
          <div className="flex-none h-[hypot(-98.2972cqw,1.69641cqh)] rotate-[89.01deg] w-[hypot(1.70282cqw,98.3036cqh)]">
            <div className="relative size-full">
              <div className="absolute inset-[-3.52%_-7.02%_-10.56%_-7.02%]">
                <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/vector-4-ee400cd9d1.svg" />
              </div>
            </div>
          </div>
        </div>
        <div className="absolute flex inset-[66.97%_26.92%_23.53%_62.19%] items-center justify-center" style={{ containerType: "size" }}>
          <div className="flex-none h-[hypot(-28.8465cqw,-71.0747cqh)] rotate-[157.89deg] w-[hypot(-71.1535cqw,28.9253cqh)]">
            <div className="relative size-full">
              <div className="absolute inset-[-3.52%_-7.02%_-10.56%_-7.02%]">
                <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/vector-5-0ddfabb83f.svg" />
              </div>
            </div>
          </div>
        </div>
        <div className="absolute flex inset-[64.66%_63.24%_25.36%_25.33%] items-center justify-center" style={{ containerType: "size" }}>
          <div className="flex-none h-[hypot(63.0427cqw,-36.868cqh)] rotate-[-120.33deg] w-[hypot(-36.9573cqw,-63.132cqh)]">
            <div className="relative size-full">
              <div className="absolute inset-[-3.52%_-7.02%_-10.56%_-7.02%]">
                <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/vector-6-8b852e34c8.svg" />
              </div>
            </div>
          </div>
        </div>
      </section>
      <div className="absolute content-stretch drop-shadow-[0px_4px_5.5px_rgba(0,0,0,0.18)] flex h-[39px] items-center justify-center left-[475px] p-[10px] rounded-[43px] top-[5414px] w-[143px]">
        <div aria-hidden className="absolute bg-[#4e4e5a] inset-0 pointer-events-none rounded-[43px]" />
        <p className="[word-break:break-word] font-medium leading-[normal] not-italic relative shrink-0 text-[13px] text-center text-white tracking-[-0.52px] whitespace-nowrap">
          UI/UX designer
        </p>
        <div className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_14px_0px_rgba(255,255,255,0.18)]" />
      </div>
    </>
  );
}
