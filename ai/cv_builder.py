"""AI CV Builder — transforms raw user data into professional CV content.

Three-tier content policy:
  TIER 1 (explicit): user stated it directly — use, rephrase, enhance freely.
  TIER 2 (inferred): professional phrasing reasonably derived from explicit info
           (e.g. job duty -> CV bullet). Allowed, must stay truthful.
  TIER 3 (needs-confirmation): numbers, achievements with metrics, certifications,
           language levels, tools, team sizes, budgets. NEVER invent.
           Either ask a short question or omit gracefully.

All methods try LLM first, fall back to rule-based generation.
"""
import json

try:
    from ai.antifab import FactRegistry, validate_output
    _ANTIFAB = True
except ImportError:
    _ANTIFAB = False


def _summary_prompt(data, lang):
    name = data.get('full_name', '')
    job = data.get('job_title', '')
    exps = data.get('experience') or []
    exp_text = '; '.join(
        '%s at %s (%s)' % (e.get('title', ''), e.get('company', ''), e.get('period', ''))
        for e in exps)
    edu = data.get('education', '')
    skills = data.get('skills') or []
    if isinstance(skills, list):
        skills = ', '.join(skills)
    target = data.get('target_job', '')
    lang_name = 'Arabic' if lang == 'ar' else 'English'
    return (
        "You are an expert CV writer. Write a Professional Summary for this candidate.\n"
        "Candidate data:\n"
        f"- Name: {name}\n- Current/Target title: {job}\n"
        f"- Experience: {exp_text or 'none listed'}\n"
        f"- Education: {edu}\n- Skills mentioned: {skills}\n"
        f"- Target job: {target or 'not specified'}\n\n"
        "STRICT RULES:\n"
        "1. Write 3-4 sentences in %s, professional natural tone.\n"
        "2. Base EVERY claim on the data above. Never invent years, numbers, companies, or achievements.\n"
        "3. FORBIDDEN generic phrases: 'hardworking', 'motivated', 'passionate', "
        "'seeking a challenging opportunity', 'dynamic individual'.\n"
        "4. If fresh graduate (no experience): write for a graduate — highlight education, "
        "training, relevant skills. Do NOT invent work experience.\n"
        "5. If experienced: focus on field, specialization, and value of contributions.\n"
        "6. If career changer: extract transferable skills without claiming direct experience.\n"
        "7. Every sentence must market the candidate with a clear purpose.\n"
        "Output ONLY the summary paragraph, no explanations." % lang_name)


def _experience_prompt(exp, lang):
    title = exp.get('title', '')
    company = exp.get('company', '')
    period = exp.get('period', '')
    raw = exp.get('desc', '')
    lang_name = 'Arabic' if lang == 'ar' else 'English'
    return (
        "You are an expert CV writer. Convert these raw job notes into professional "
        "CV bullet points in %s.\n"
        "Job: %s at %s (%s)\nRaw notes: %s\n\n"
        "STRICT RULES:\n"
        "1. Output 3-5 bullet points, each starting with a strong action verb.\n"
        "2. DISTINGUISH responsibilities (normal duties) from achievements (proven results).\n"
        "3. If the notes mention a number/metric, use it EXACTLY as given.\n"
        "4. If NO numbers are given, write professional responsibility bullets WITHOUT "
        "inventing percentages, amounts, or counts.\n"
        "5. Adapt phrasing to the actual job, sector, and seniority. No copy-paste templates.\n"
        "6. Keep each bullet to 1-2 lines.\n"
        "Output ONLY the bullets, one per line, starting with '- '." %
        (lang_name, title, company, period, raw))


def _achievements_prompt(notes, lang):
    lang_name = 'Arabic' if lang == 'ar' else 'English'
    return (
        "You are an expert CV writer. Turn these rough achievement notes into "
        "professional CV achievement statements in %s.\n"
        "Notes: %s\n\n"
        "STRICT RULES:\n"
        "1. If a note contains a number/result, use it precisely.\n"
        "2. If NO number is given, do NOT invent one. Write it as a professional "
        "contribution instead.\n"
        "3. If a note is too vague, convert to responsibility-style bullet or drop it.\n"
        "Output ONLY the achievements, one per line, starting with '- '." %
        (lang_name, notes))


def _skills_prompt(data, lang):
    job = data.get('job_title', '')
    exps = data.get('experience') or []
    exp_text = '; '.join('%s: %s' % (e.get('title', ''), e.get('desc', '')) for e in exps)
    edu = data.get('education', '')
    user_skills = data.get('skills') or []
    if isinstance(user_skills, list):
        user_skills = ', '.join(user_skills)
    lang_name = 'Arabic' if lang == 'ar' else 'English'
    return (
        "You are an expert CV writer. Suggest relevant skills for this candidate in %s.\n"
        "Job title: %s\nExperience: %s\nEducation: %s\n"
        "Skills user already listed: %s\n\n"
        "STRICT RULES:\n"
        "1. Suggest 8-12 skills, grouped into ONLY relevant categories.\n"
        "2. Tag each: [PROVEN] if user stated it, [INFERRED] if reasonably derived.\n"
        "3. NEVER add advanced technical skills or certifications without evidence.\n"
        "Output format:\nCategory: skill [TAG], skill [TAG]\n"
        "Output ONLY the categorized skills." %
        (lang_name, job, exp_text or 'none', edu, user_skills or 'none'))


def _review_prompt(cv_json, lang):
    lang_name = 'Arabic' if lang == 'ar' else 'English'
    return (
        "You are a senior CV editor. Review this CV data (JSON) and return an improved version.\n"
        "CV: %s\n\n"
        "Check: duplicates, grammar, tense consistency, date formats, bullet importance order, "
        "real achievements, no empty sections, no filler, no contradictions, "
        "every claim traceable to user input.\n\n"
        "Return ONLY valid JSON with the same structure, improved values, plus a "
        '"_review_notes" array. Language: %s.' % (cv_json, lang_name))


class AIBuilder:
    def __init__(self, llm=None):
        self.llm = llm

    async def _gen(self, system, user, fallback, registry=None, context='general'):
        if self.llm:
            try:
                out = await self.llm(system, user)
                if out and len(out.strip()) > 10:
                    cleaned = out.strip()
                    # MECHANICAL VALIDATION: check against facts
                    if _ANTIFAB and registry is not None:
                        valid, violations = validate_output(cleaned, registry, context)
                        if not valid:
                            # Log violations and fall back to rule-based
                            return fallback
                    # Reject outputs that merely echo the input without adding value
                    # (compare normalized word overlap)
                    import re as _re
                    def _words(t):
                        return set(_re.findall(r'\w+', t.lower()))
                    uw, ow = _words(user), _words(cleaned)
                    if uw and ow:
                        # If output adds <15% new words beyond input, treat as no-value
                        new_ratio = len(ow - uw) / max(len(ow), 1)
                        if new_ratio < 0.15 and len(cleaned) < len(user) * 1.5:
                            return fallback
                    return cleaned
            except Exception:
                # Any LLM failure (timeout, API error, empty, malformed):
                # fall through to rule-based. Never leak keys in logs.
                pass
        return fallback

    async def write_summary(self, data, lang='ar'):
        from ai.engine import rule_summary
        system = "You are a professional CV writer. Follow the rules exactly."
        registry = FactRegistry(data) if _ANTIFAB else None
        fallback = rule_summary(data, lang)
        return await self._gen(system, _summary_prompt(data, lang), fallback,
                               registry=registry, context='summary')

    async def tailor_summary(self, data, jd_text, lang='ar'):
        """Rewrite summary emphasizing JD-relevant REAL qualifications only."""
        from ai.jd_match import extract_requirements, match_against_user
        from ai.engine import rule_summary
        reqs = extract_requirements(jd_text)
        match = match_against_user(reqs, data)
        if not match['covered']:
            return None, 'no_overlap'
        covered_str = ', '.join(match['covered'][:8])
        system = ("You are a professional CV writer. Rewrite to emphasize "
                  "listed qualifications. STRICT: use ONLY facts from original "
                  "data. Do NOT add companies, dates, numbers, or skills.")
        orig = data.get('summary') or rule_summary(data, lang)
        langname = 'Arabic' if lang == 'ar' else 'English'
        prompt = (f"Original: {orig}\nEmphasize: {covered_str}\n"
                  f"Language: {langname}\nRewrite in 2-3 sentences.")
        reg = None
        try:
            from ai.antifab import FactRegistry
            reg = FactRegistry(data)
        except ImportError:
            pass
        out = await self._gen(system, prompt, orig, registry=reg, context='summary')
        return out, 'tailored'

    async def tailor_experience(self, exp, jd_text, lang='ar', parent_data=None):
        """Rewrite experience bullets to emphasize JD-relevant REAL work.
        Preserves original desc. Never invents."""
        from ai.jd_match import extract_requirements, match_against_user
        reqs = extract_requirements(jd_text)
        # Build mini-data for matching this experience
        mini = {'experience': [exp], 'skills': [], 'summary': '', 'education': ''}
        match = match_against_user(reqs, mini)
        if not match['covered']:
            return None, 'no_overlap'
        covered_str = ', '.join(match['covered'][:6])
        system = ("You are a professional CV writer. Rewrite these bullet points "
                  "to emphasize the listed qualifications. STRICT: use ONLY facts "
                  "from the original bullets. Do NOT add numbers, companies, or "
                  "responsibilities not in the original. Keep same bullet count.")
        orig_desc = exp.get('desc', '')
        langname = 'Arabic' if lang == 'ar' else 'English'
        prompt = (f"Original bullets:\n{orig_desc}\n"
                  f"Emphasize: {covered_str}\nLanguage: {langname}\n"
                  f"Rewrite each bullet professionally, same count.")
        reg = None
        try:
            from ai.antifab import FactRegistry
            reg = FactRegistry(parent_data or {'experience': [exp]})
        except ImportError:
            pass
        out = await self._gen(system, prompt, '', registry=reg, context='experience')
        if out:
            bullets = [l.strip().lstrip('-• ') for l in out.split('\n') if l.strip()]
            # Safety: don't return more bullets than original
            orig_count = len([l for l in orig_desc.split('\n') if l.strip()])
            bullets = bullets[:max(orig_count, 1)]
            if bullets:
                return bullets, 'tailored'
        return None, 'fallback'

    async def enhance_experience(self, exp, lang='ar', parent_data=None):
        from ai.engine import rule_improve_experience
        system = "You are a professional CV writer. Follow the rules exactly."
        raw = exp.get('desc', '')
        registry = FactRegistry(parent_data) if (_ANTIFAB and parent_data) else None

        def _rule_bullets(text):
            # Split rough notes into clean bullets without inventing facts
            import re as _re
            parts = _re.split(r'[\n؛;]+|\s+[وو]\s+(?=[^\s])', text or '')
            # also try splitting on '،' if it yields multiple meaningful parts
            if len(parts) <= 1 and '،' in (text or ''):
                alt = [s.strip() for s in text.split('،') if s.strip()]
                if len(alt) > 1:
                    parts = alt
            seen, out = set(), []
            for s in parts:
                s = s.strip(' •-\t،,')
                if s and s not in seen and len(s) > 2:
                    seen.add(s)
                    out.append(s)
            return out[:6]

        out = await self._gen(system, _experience_prompt(exp, lang), '',
                                registry=registry, context='experience')
        if out:
            lines = [l.strip().lstrip('-• ').strip()
                     for l in out.split('\n') if l.strip()]
            bullets = [l for l in lines if l][:6]
        else:
            bullets = _rule_bullets(rule_improve_experience(raw, lang))
        # Fallback to original raw if everything empty
        if not bullets and raw.strip():
            bullets = [raw.strip()]
        return bullets

    async def build_achievements(self, notes, lang='ar'):
        if not notes or not notes.strip():
            return []
        system = "You are a professional CV writer. Follow the rules exactly."
        out = await self._gen(system, _achievements_prompt(notes, lang), '')
        lines = [l.strip().lstrip('-• ').strip() for l in out.split('\n') if l.strip()]
        return [l for l in lines if l][:6]

    async def infer_skills(self, data, lang='ar'):
        from ai.engine import suggest_skills_list
        field = data.get('field', 'general') or 'general'
        system = "You are a professional CV writer. Follow the rules exactly."
        return await self._gen(system, _skills_prompt(data, lang),
                               ', '.join(suggest_skills_list(field, 'mid', lang)))

    async def review(self, cv_data, lang='ar'):
        safe = {k: v for k, v in cv_data.items()
                if k not in ('_review_notes', 'user_id', 'order_id')}
        try:
            cv_json = json.dumps(safe, ensure_ascii=False, default=str)[:6000]
        except Exception:
            return cv_data, ['review skipped: serialization failed']
        system = "You are a senior CV editor. Return only valid JSON."
        out = await self._gen(system, _review_prompt(cv_json, lang), '')
        if not out:
            return cv_data, ['review skipped: LLM unavailable']
        try:
            txt = out.strip()
            if txt.startswith('```'):
                txt = txt.split('\n', 1)[1].rsplit('```', 1)[0]
            improved = json.loads(txt)
            if not isinstance(improved, dict):
                return cv_data, ['review rejected: not a dict']
            notes = improved.pop('_review_notes', [])
            merged = dict(cv_data)
            # Only accept improvements for known keys with sane values
            allowed = {'summary', 'experience', 'skills', 'education',
                       'languages', 'certs', 'courses', 'projects', 'achievements'}
            for k, v in improved.items():
                if k not in allowed or not v:
                    continue
                # Sanity: don't accept values that are drastically different in a
                # suspicious way (e.g. empty original -> long invented text is OK
                # only for summary which AI generates; for others require overlap)
                if k == 'experience' and not isinstance(v, list):
                    continue
                if isinstance(v, str) and len(v) > 5000:
                    continue
                merged[k] = v
            return merged, notes if isinstance(notes, list) else [str(notes)]
        except Exception as e:
            return cv_data, ['review parse failed: %s' % e]

    async def build_full_cv(self, data, lang='ar'):
        report = []
        out = dict(data)
        if not data.get('summary') or len(data.get('summary', '')) < 50:
            out['summary'] = await self.write_summary(data, lang)
            report.append('summary: AI-generated')
        else:
            report.append('summary: user-provided')
        # JD tailoring (optional)
        _jd = (data.get('job_description') or '').strip()
        if len(_jd) > 20:
            try:
                from ai.jd_match import tailor_cv
                _tailored, _jdr = tailor_cv(out, _jd, lang)
                if _jdr.get('reordered'):
                    out['experience'] = _tailored.get('experience', out.get('experience'))
                    report.append('jd: experience reordered')
                _ts, _tst = await self.tailor_summary(out, _jd, lang)
                if _ts and _tst == 'tailored':
                    out['summary'] = _ts
                    report.append('jd: summary tailored %.0f%%' % (_jdr['coverage_ratio'] * 100))
                else:
                    report.append('jd: analyzed %.0f%%, no rewrite' % (_jdr['coverage_ratio'] * 100))
                # Tailor experience bullets (preserve originals)
                _tailored_count = 0
                for _i, _exp in enumerate(out.get('experience') or []):
                    if _exp.get('desc'):
                        _tb, _tbs = await self.tailor_experience(
                            _exp, _jd, lang, parent_data=data)
                        if _tb and _tbs == 'tailored':
                            _exp = dict(_exp)
                            if not _exp.get('desc_original'):
                                _exp['desc_original'] = _exp.get('desc')
                            _exp['desc'] = '\n'.join(_tb)
                            _exp['_jd_tailored'] = True
                            out['experience'][_i] = _exp
                            _tailored_count += 1
                if _tailored_count:
                    report.append(f'jd: {_tailored_count} experience(s) tailored')
                import json as _jj
                out['_jd_match_report'] = _jj.dumps(
                    {'covered': _jdr['covered_terms'][:10],
                     'missing': _jdr['missing_terms'][:10],
                     'needs_input': _jdr['needs_user_input'][:5]},
                    ensure_ascii=False)
            except Exception as _e:
                report.append('jd: failed, untailored')
        exps = out.get('experience') or []
        for i, exp in enumerate(exps):
            if exp.get('desc'):
                bullets = await self.enhance_experience(exp, lang, parent_data=data)
                if bullets:
                    exps[i] = dict(exp, desc='\n'.join(bullets), desc_original=exp.get('desc'))
                    report.append('experience[%d]: %d bullets' % (i, len(bullets)))
        out['experience'] = exps
        # Build achievements from user notes if provided
        ach_notes = data.get('achievements') or data.get('achievements_raw') or ''
        if ach_notes and isinstance(ach_notes, str) and ach_notes.strip():
            achs = await self.build_achievements(ach_notes, lang)
            if achs:
                out['achievements'] = achs
                report.append('achievements: %d items' % len(achs))
        # AI skill suggestions — merge into skills so they reach the PDF
        ai_skills = await self.infer_skills(data, lang)
        out['skills_ai_suggestion'] = ai_skills
        cur = out.get('skills') or []
        if isinstance(cur, str):
            cur = [s.strip() for s in cur.replace(',', '\n').split('\n') if s.strip()]
        # Parse AI suggestions (strip [PROVEN]/[INFERRED] tags for clean display)
        import re as _re
        ai_list = []
        if ai_skills and isinstance(ai_skills, str):
            for part in _re.split(r'[,\n]', ai_skills):
                s = _re.sub(r'\[(PROVEN|INFERRED)\]', '', part).strip(' -•')
                # skip category headers like "Technical:"
                if ':' in s and len(s.split(':')[0]) < 30:
                    s = s.split(':', 1)[1].strip()
                    s = _re.sub(r'\[(PROVEN|INFERRED)\]', '', s).strip()
                if s and len(s) < 60:
                    ai_list.append(s)
        # Merge: keep user's skills first, add AI ones not already present (max 12 total)
        merged = list(cur)
        cur_lower = {s.lower() for s in cur}
        for s in ai_list:
            if s.lower() not in cur_lower and len(merged) < 12:
                merged.append(s)
                cur_lower.add(s.lower())
        if len(merged) > len(cur):
            out['skills'] = merged
            report.append('skills: %d user + %d AI = %d total' %
                          (len(cur), len(merged) - len(cur), len(merged)))
        else:
            report.append('skills: kept user skills (%d)' % len(cur))
        out, notes = await self.review(out, lang)
        report.append('review: %d notes' % len(notes))
        out['_review_notes'] = notes
        # MANDATORY FINAL REVIEW: 10-point checklist before PDF
        try:
            from ai.final_review import must_pass_review
            from ai.antifab import FactRegistry
            reg = FactRegistry(data)
            out, review_issues = must_pass_review(out, reg)
            if review_issues:
                report.append('final_review: %d minor issues' % len(review_issues))
            else:
                report.append('final_review: PASSED')
        except ValueError as e:
            # Critical failure: fall back to original data
            report.append('final_review: FAILED - %s' % e)
            out = dict(data)
        except ImportError:
            report.append('final_review: skipped (module missing)')
        return out, report
