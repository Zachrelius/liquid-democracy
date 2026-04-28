import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';

export default function Why() {
  return (
    <PublicLayout>
      <article className="max-w-3xl mx-auto px-6 py-16 sm:py-20 text-[#2C3E50]">
        <header className="mb-12">
          <p className="text-sm font-medium text-[#2E75B6] uppercase tracking-wider">
            The longer answer
          </p>
          <h1 className="mt-2 text-4xl sm:text-5xl font-semibold text-[#1B3A5C] tracking-tight">
            Why this project
          </h1>
        </header>

        <div className="space-y-4 text-base leading-relaxed text-[#2C3E50]">
          <p>
            I first heard the idea of liquid democracy years ago, in Adrian
            Hon's{' '}
            <a
              href="https://www.goodreads.com/book/show/18490293-a-history-of-the-future-in-100-objects"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#2E75B6] hover:text-[#1B3A5C] underline italic"
            >
              A History of the Future in 100 Objects
            </a>
            . It was a side note in a fictional 21st-century timeline: the
            assumption that some future society would naturally vote on
            issues directly when they cared, and delegate to people they
            trusted on the things they didn't. I read it and thought,
            obviously. That's how this should work. The idea didn't leave.
          </p>
          <p>
            For a while I thought the way to do something with it was to
            write about it. I'd been listening to{' '}
            <a
              href="https://www.cognitiverevolution.ai"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#2E75B6] hover:text-[#1B3A5C] underline italic"
            >
              The Cognitive Revolution
            </a>{' '}
            with Nathan Labenz, where one of the recurring themes is that
            our scarcest resource right now isn't compute or talent or
            capital, it's a positive vision for the future. Most stories
            about where we're headed are bleak; the few that aren't tend
            to be naive. I'd read Stephen Markley's{' '}
            <a
              href="https://www.goodreads.com/book/show/60806778-the-deluge"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#2E75B6] hover:text-[#1B3A5C] underline italic"
            >
              The Deluge
            </a>{' '}
            and admired what it did with climate change, the way it
            threaded a real argument through interlocking character
            vignettes, and I started toying with writing something similar
            set against a hopeful AI transition, with a liquid democracy
            party rising to power as one of the through-lines.
          </p>
          <p>
            I quickly realized that I'm not much of a writer, and that I
            was more interested in liquid democracy in real life than in
            a novel. I started researching past liquid democracy projects
            to learn what systems they'd used that I could advocate for
            trials of and was surprised to learn there wasn't a modern
            production-quality liquid democracy software that small
            organizations could actually use. So, with a lot of help from
            Claude Code, I'm building it.
          </p>
        </div>

        <Section title="Why now">
          <p>
            The political weight ordinary people have today rests on a
            foundation that's going to get weaker. The reason I'm spending
            time on this is that I think it's worth trying to show that
            democratic institutions can be radically more responsive while
            we the people still have some power.
          </p>
          <p>
            The argument runs like this. Most developed countries have, on
            the whole, treated their populations reasonably well over the
            last century or two. Not perfectly, not equally, but better
            than the historical baseline. There are a lot of reasons for
            this, but one of the load-bearing ones is that those countries
            needed their populations. They needed educated workers to run
            complex economies, healthy young people to fight wars, and
            broadly contented citizens who wouldn't revolt. Universal
            education, social safety nets, and the gradual expansion of
            the franchise weren't gifts; they were responses to the fact
            that ordinary people were genuinely valuable and could
            withhold their cooperation if mistreated.
          </p>
          <p>
            That equation is going to change. I don't know whether the
            timeline is five years or twenty, and I don't think anyone
            honestly does. But the direction is clear: as AI systems
            become capable of more of the work that gives ordinary humans
            economic and strategic value, the structural reason
            governments have to be responsive to ordinary people gets
            weaker. The institutions we have were built for the old
            equation. If those institutions don't get more responsive,
            more granular, and more accountable before the equation
            shifts, the slide back toward the historical baseline could
            happen fast.
          </p>
          <p>
            I think the move that matters is making political institutions
            more responsive while ordinary people still have the leverage
            to demand they be. Liquid democracy is one way of doing that.
            Probably not the only way. Probably not even the best way for
            every context. But it's a concrete, buildable, testable shape
            for the kind of institution that could survive the transition.
          </p>
        </Section>

        <Section title="Why this shape">
          <p>
            Liquid democracy fits the moment for a few reasons. It
            acknowledges that most people don't want to spend their lives
            following politics and gives them a way to participate
            seriously without investing more time than they want. It
            distributes accountability across many small relationships of
            trust instead of concentrating it in a few elections that come
            every few years. It's correctable in real time, which matters
            more as the pace of consequential decisions accelerates. And
            it scales down: it can run inside a thirty-person co-op or a
            thousand-person organization just as well as a city. Many
            reform proposals are specific to the scale they were designed
            for. This one could be useful in a lot of places.
          </p>
        </Section>

        <Section title="How I think it goes">
          <p>
            The path I described on the About page goes in stages: small
            organizations first, local government next. There's a
            potential third stage worth mentioning, even though it's
            further out and more speculative.
          </p>
          <p>
            If liquid democracy works at municipal scale, the natural next
            step is for it to enter representative legislatures through
            the front door: a party or caucus whose candidates run on the
            explicit pledge to vote according to what their constituents
            have decided through the platform. Not "I'll listen to my
            constituents" in the usual hand-wavy sense, but a binding
            commitment to follow a verifiable, public, ongoing vote of the
            people they represent. Even a small caucus operating this way
            in a closely divided legislature could be decisive on
            individual bills. I'm not pretending this is around the corner.
            But it's a real possibility worth building toward, and naming
            it makes the earlier stages legible as part of a longer arc
            rather than ends in themselves.
          </p>
        </Section>

        <Section title="Why me, then">
          <p>
            I'm not a politician, I'm not an academic, I don't have a
            constituency. I'm a person who thought this was a good idea
            for a long time, assumed someone had already built it, and
            was surprised when I looked and nobody really had. The reason
            nobody had is straightforward: until very recently, building
            something like this would have been expensive and there wasn't
            money in it. AI coding tools changed that in the last few
            months, building it became cheap, and the question of whether
            anyone would pay for it stopped being a gating one. I happened
            to be paying attention when that shifted and picked this to
            focus. Not a heroic origin story, just how I got here.
          </p>
        </Section>

        <Section title="Looking further out">
          <p>
            The version of liquid democracy I'm building is for humans.
            That's a choice, and it's one that gets less obvious the
            further out you look.
          </p>
          <p>
            I don't think humans should rule over our intelligent creations
            forever. I also don't think we can just let any sufficiently
            capable digital being vote. Digital beings can be copied almost
            instantly and will someday soon surpass human populations.
            There's a philosophical compromise I think is closer to right:
            Earth is the place humans evolved for, the only place we're
            adapted to, and human political control of Earth is something
            we have a defensible claim to even in a world full of minds
            that can outthink us. The frontier, space, other planets and
            eventually other stars will have different social contracts
            between new beings. But hopefully Earth gets to be ours, on
            terms that let us live flourishing lives of our choosing,
            while preserving the other species of Earth's biosphere.
          </p>
          <p>
            It's not a fully worked-out position. But it's the place I
            keep landing when I think about how this scales out beyond the
            next few decades, and I'd rather put it on the page in rough
            form than pretend I haven't thought about it.
          </p>
        </Section>

        <div className="mt-12 pt-8 border-t border-gray-200 flex flex-wrap items-center gap-3">
          <Link
            to="/about"
            className="inline-flex items-center px-5 py-2.5 bg-white text-[#1B3A5C] text-sm font-medium rounded-lg border border-gray-300 hover:border-[#2E75B6] hover:text-[#2E75B6] transition-colors"
          >
            Back to About
          </Link>
          <Link
            to="/demo"
            className="inline-flex items-center px-5 py-2.5 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors"
          >
            Try the demo
          </Link>
        </div>
      </article>
    </PublicLayout>
  );
}

function Section({ title, children }) {
  return (
    <section className="mt-12">
      <h2 className="text-2xl font-semibold text-[#1B3A5C] mb-4 tracking-tight">
        {title}
      </h2>
      <div className="space-y-4 text-base leading-relaxed text-[#2C3E50]">
        {children}
      </div>
    </section>
  );
}