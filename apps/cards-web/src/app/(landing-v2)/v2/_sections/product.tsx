/* eslint-disable @next/next/no-img-element -- static SVG icons from the design; next/image adds nothing for vectors */
import Image from "next/image";
import Link from "next/link";

export function ProductSection() {
  return (
    <>
      <section id="product" className="absolute bg-[#e3edf4] h-[1129px] left-[39px] overflow-clip rounded-[8px] shadow-[0px_4px_0px_0px_rgba(0,0,0,0.13)] top-[1129px] w-[1362px]">
        <div className="absolute h-[684px] left-[318px] top-[212px] w-[734px]">
          <div className="absolute inset-[-0.73%_0_0_0]">
            <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/group-1597880893-fb438652f5.svg" />
          </div>
        </div>
        <div className="absolute flex h-[734px] items-center justify-center left-[343px] top-[177px] w-[684px]">
          <div className="-rotate-90 flex-none">
            <div className="h-[684px] relative w-[734px]">
              <div className="absolute inset-[-0.73%_0_0_0]">
                <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/group-1597880894-c9c39592c7.svg" />
              </div>
            </div>
          </div>
        </div>
        {/* Card glow: the design's 0 4px 250px 76px #5cbbfb shadow as a blurred layer; Chrome clamps
            box-shadow blur this large and renders it as a hard-edged rectangle. */}
        <div aria-hidden className="absolute bg-[#5cbbfb] blur-[125px] h-[730px] left-[374px] rounded-bl-[117px] rounded-br-[117px] rounded-tl-[147px] rounded-tr-[147px] top-[183px] w-[622px]" />
        <div className="absolute h-[578px] left-[450px] overflow-clip rounded-bl-[41px] rounded-br-[41px] rounded-tl-[71px] rounded-tr-[71px] shadow-[0px_4px_20px_0px_rgba(0,0,0,0.25)] top-[255px] w-[470px]">
          <div aria-hidden className="absolute bg-white inset-0 pointer-events-none rounded-bl-[41px] rounded-br-[41px] rounded-tl-[71px] rounded-tr-[71px]" />
          <div className="absolute h-[442px] left-[16px] overflow-clip rounded-[62px] top-[17px] w-[437px]">
            <div className="absolute h-[720px] left-[-39px] pointer-events-none top-[-120px] w-[480px]">
              <div className="absolute inset-0 overflow-hidden">
                <Image alt="" className="absolute left-[5.35%] max-w-none size-full top-[6.83%]" src="/assets/landing-v2/image-2651-f7979bcfa8.png" width={480} height={720} />
              </div>
              <div className="absolute inset-0 rounded-[inherit] shadow-[inset_-1px_4px_46px_0px_rgba(0,0,0,0.25)]" />
            </div>
            <div className="absolute border-[#a5a5a5] border-[0.3px] border-solid h-[30px] left-[331px] pointer-events-none rounded-[31px] top-[32px] w-[77px]">
              <div aria-hidden className="absolute bg-white inset-0 rounded-[31px]" />
              <div className="absolute inset-0 rounded-[inherit] shadow-[inset_0px_4px_9px_0px_rgba(0,0,0,0.17)]" />
            </div>
            <p className="-translate-x-1/2 [word-break:break-word] absolute font-medium leading-[normal] left-[375px] not-italic text-[#a2a2a2] text-[14px] text-center top-[38px] tracking-[-0.56px] whitespace-nowrap">
              Online
            </p>
            <div className="absolute left-[339px] size-[12px] top-[41px]">
              <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/ellipse-14343-b6375e7ceb.svg" />
            </div>
          </div>
          <div className="absolute left-[16px] size-[68px] top-[483px]">
            <div className="absolute inset-[-195.59%_-201.47%_-207.35%_-201.47%]">
              <Image alt="" className="block max-w-none size-full" height={342} src="/assets/landing-v2/ellipse-14342-023fd59896.png" width={342} />
            </div>
          </div>
          <div className="absolute left-[63px] size-[16px] top-[533px]">
            <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/ellipse-14346-0efea8bdfb.svg" />
          </div>
          <Link href="/create" className="absolute content-stretch drop-shadow-[0px_4px_9.5px_rgba(0,0,0,0.61)] flex h-[55px] items-center justify-center left-[266px] p-[10px] rounded-[43px] top-[487px] w-[187px]">
            <span aria-hidden className="absolute bg-[#262627] inset-0 pointer-events-none rounded-[43px]" />
            <span className="[word-break:break-word] font-normal leading-[normal] not-italic relative shrink-0 text-[20px] text-center text-white tracking-[-0.8px] whitespace-nowrap">
              Make your own
            </span>
            <span className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_12px_0px_rgba(255,255,255,0.25)]" />
          </Link>
          <p className="-translate-x-1/2 [word-break:break-word] absolute font-semibold leading-[normal] left-[117px] not-italic text-[#121214] text-[17px] text-center top-[497px] tracking-[-0.68px] whitespace-nowrap">
            @john
          </p>
          <p className="-translate-x-1/2 [word-break:break-word] absolute font-medium leading-[normal] left-[131px] not-italic text-[#6b6969] text-[10px] text-center top-[521px] tracking-[-0.4px] whitespace-nowrap">
            Product Designer
          </p>
          <div className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_5px_0px_rgba(0,0,0,0.4)]" />
        </div>
        <div className="absolute bg-white border border-[#d7d7d7] border-solid h-[107px] left-[150px] rounded-[132px] top-[318px] w-[239px]" />
        <div className="absolute bg-white border border-[#d7d7d7] border-solid h-[107px] left-[973px] rounded-[132px] top-[318px] w-[254px]" />
        <div className="absolute bg-white border border-[#d7d7d7] border-solid h-[107px] left-[31px] rounded-[132px] top-[478px] w-[244px]" />
        <div className="absolute bg-white border border-[#d7d7d7] border-solid h-[107px] left-[1092px] rounded-[132px] top-[474px] w-[239px]" />
        <div className="absolute bg-white border border-[#d7d7d7] border-solid h-[107px] left-[113px] rounded-[132px] top-[636px] w-[254px]" />
        <div className="absolute bg-white border border-[#d7d7d7] border-solid h-[107px] left-[973px] rounded-[132px] top-[636px] w-[254px]" />
        <div className="absolute left-[159px] size-[88px] top-[328px]">
          <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/ellipse-14355-855bb43f48.svg" />
        </div>
        <div className="absolute left-[983px] size-[88px] top-[328px]">
          <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/ellipse-14361-37bfc43233.svg" />
        </div>
        <div className="absolute left-[1104px] size-[88px] top-[484px]">
          <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/ellipse-14361-37bfc43233.svg" />
        </div>
        <div className="absolute left-[983px] size-[88px] top-[645px]">
          <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/ellipse-14361-37bfc43233.svg" />
        </div>
        <div className="absolute left-[42px] size-[88px] top-[488px]">
          <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/ellipse-14361-37bfc43233.svg" />
        </div>
        <div className="absolute left-[124px] size-[88px] top-[646px]">
          <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/ellipse-14361-37bfc43233.svg" />
        </div>
        <div className="absolute left-[181px] size-[44px] top-[350px]">
          <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/mdi-eye-d6422c5be2.svg" />
        </div>
        <div className="absolute left-[59px] size-[54px] top-[505px]">
          <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/ant-design-team-outlined-d2c86eb292.svg" />
        </div>
        <div className="absolute left-[142px] size-[52px] top-[664px]">
          <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/weui-discover-filled-6e4d92d301.svg" />
        </div>
        <div className="absolute left-[1006px] overflow-clip size-[42px] top-[351px]">
          <div className="absolute inset-[12.5%]">
            <div className="absolute inset-[-3.17%]">
              <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/group-f488b23a99.svg" />
            </div>
          </div>
        </div>
        <div className="absolute left-[1127px] size-[42px] top-[507px]">
          <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/pepicons-pencil-electricity-793898b504.svg" />
        </div>
        <p className="-translate-x-1/2 [word-break:break-word] absolute font-semibold leading-[1.178] left-[296px] not-italic text-[18px] text-black text-center top-[339px] tracking-[-0.9px] whitespace-nowrap">
          Showcase
        </p>
        <p className="[word-break:break-word] absolute font-medium leading-[normal] left-[255px] not-italic text-[#7a7a7a] text-[12px] top-[360px] tracking-[-0.6px] w-[98px]">
          Your work, projects, and achievements.
        </p>
        <p className="[word-break:break-word] absolute font-medium leading-[normal] left-[1082px] not-italic text-[#7a7a7a] text-[12px] top-[360px] tracking-[-0.6px] w-[121px]">
          Link your GitHub, LinkedIn, portfolio and more.
        </p>
        <p className="[word-break:break-word] absolute font-medium leading-[normal] left-[1199px] not-italic text-[#7a7a7a] text-[12px] top-[519px] tracking-[-0.6px] w-[108px]">
          Let your skills speak for you.
        </p>
        <p className="[word-break:break-word] absolute font-medium leading-[normal] left-[1084px] not-italic text-[#7a7a7a] text-[12px] top-[687px] tracking-[-0.6px] w-[108px]">
          More visibility. More possibilities.
        </p>
        <p className="[word-break:break-word] absolute font-medium leading-[normal] left-[222px] not-italic text-[#7a7a7a] text-[12px] top-[672px] tracking-[-0.6px] w-[138px]">
          Be matched with collaborators, creators and opportunities.
        </p>
        <p className="[word-break:break-word] absolute font-medium leading-[normal] left-[136px] not-italic text-[#7a7a7a] text-[12px] top-[519px] tracking-[-0.6px] w-[125px]">
          Get found by the right people and opportunities.
        </p>
        <p className="-translate-x-1/2 [word-break:break-word] absolute font-semibold leading-[1.178] left-[181.5px] not-italic text-[18px] text-black text-center top-[498px] tracking-[-0.9px] whitespace-nowrap">
          Collaborate
        </p>
        <p className="-translate-x-1/2 [word-break:break-word] absolute font-semibold leading-[1.178] left-[271px] not-italic text-[18px] text-black text-center top-[651px] tracking-[-0.9px] whitespace-nowrap">
          AI Discovery
        </p>
        <p className="-translate-x-1/2 [word-break:break-word] absolute font-semibold leading-[1.178] left-[1114.5px] not-italic text-[18px] text-black text-center top-[338px] tracking-[-0.9px] whitespace-nowrap">
          Connect
        </p>
        <p className="-translate-x-1/2 [word-break:break-word] absolute font-semibold leading-[1.178] left-[1219px] not-italic text-[18px] text-black text-center top-[499px] tracking-[-0.9px] whitespace-nowrap">
          Skills
        </p>
        <p className="-translate-x-1/2 [word-break:break-word] absolute font-semibold leading-[1.178] left-[1137px] not-italic text-[18px] text-black text-center top-[662px] tracking-[-0.9px] whitespace-nowrap">
          Opportunities
        </p>
      </section>
      <div className="absolute bg-[#fffefe] blur-[85.5px] h-[280px] left-[206px] top-[989px] w-[1023px]" />
      <div className="absolute h-[90px] left-[564px] top-[1995px] w-[320px]">
        <div className="absolute inset-[-30%_-9.69%_-38.89%_-9.69%]">
          <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/group-1597880895-27620fa2df.svg" />
        </div>
      </div>
      <div className="absolute h-[36px] left-[1045px] top-[1800px] w-[40px]">
        <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/fa-solid-brain-e2de72b3e6.svg" />
      </div>
    </>
  );
}
